"""
job_manager.py — In-process background job manager for ingest pipeline.

Provides a job-based architecture without requiring external infrastructure
(Redis, Celery, etc.). Jobs run as asyncio background tasks with real-time
stage tracking that the frontend can poll.

Job lifecycle:
    pending → validating → fetching_metadata → downloading_audio →
    transcribing → chunking → embedding → storing → completed | failed
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class JobStage(str, Enum):
    PENDING = "pending"
    VALIDATING = "validating"
    FETCHING_METADATA = "fetching_metadata"
    DOWNLOADING_AUDIO = "downloading_audio"
    TRANSCRIBING = "transcribing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"


# Ordered list for progress calculation
_STAGE_ORDER = [
    JobStage.PENDING,
    JobStage.VALIDATING,
    JobStage.FETCHING_METADATA,
    JobStage.DOWNLOADING_AUDIO,
    JobStage.TRANSCRIBING,
    JobStage.CHUNKING,
    JobStage.EMBEDDING,
    JobStage.STORING,
    JobStage.COMPLETED,
]

STAGE_LABELS = {
    JobStage.PENDING: "Queued",
    JobStage.VALIDATING: "Validating URLs",
    JobStage.FETCHING_METADATA: "Fetching video metadata",
    JobStage.DOWNLOADING_AUDIO: "Downloading audio",
    JobStage.TRANSCRIBING: "Extracting transcript",
    JobStage.CHUNKING: "Chunking transcript",
    JobStage.EMBEDDING: "Generating embeddings",
    JobStage.STORING: "Storing in vector database",
    JobStage.COMPLETED: "Ready to chat",
    JobStage.FAILED: "Failed",
}


@dataclass
class JobState:
    job_id: str
    session_id: str
    youtube_url: str
    instagram_url: str
    preferred_language: Optional[str]
    stage: JobStage = JobStage.PENDING
    stage_label: str = "Queued"
    progress: int = 0  # 0–100
    error: Optional[str] = None
    error_stage: Optional[str] = None
    result: Optional[dict] = None  # IngestResponse-like dict when completed
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    _task: Optional[asyncio.Task] = field(default=None, repr=False)

    def to_dict(self) -> dict:
        """Serialize for API response (excludes internal _task)."""
        return {
            "job_id": self.job_id,
            "session_id": self.session_id,
            "stage": self.stage.value,
            "stage_label": self.stage_label,
            "progress": self.progress,
            "error": self.error,
            "error_stage": self.error_stage,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------
_jobs: dict[str, JobState] = {}
MAX_JOBS = 200  # evict oldest when exceeded


def create_job(
    session_id: str,
    youtube_url: str,
    instagram_url: str,
    preferred_language: Optional[str] = None,
) -> JobState:
    """Create and register a new job."""
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job = JobState(
        job_id=job_id,
        session_id=session_id,
        youtube_url=youtube_url,
        instagram_url=instagram_url,
        preferred_language=preferred_language,
    )
    _jobs[job_id] = job

    # Evict oldest jobs if over capacity
    if len(_jobs) > MAX_JOBS:
        oldest_key = next(iter(_jobs))
        old_job = _jobs.pop(oldest_key)
        if old_job._task and not old_job._task.done():
            old_job._task.cancel()

    logger.info("[JobManager] Created job=%s session=%s", job_id, session_id)
    return job


def get_job(job_id: str) -> Optional[JobState]:
    """Get a job by ID."""
    return _jobs.get(job_id)


def update_job_stage(job_id: str, stage: JobStage) -> None:
    """Update job to a new stage with auto-calculated progress."""
    job = _jobs.get(job_id)
    if not job:
        return
    job.stage = stage
    job.stage_label = STAGE_LABELS.get(stage, stage.value)
    job.updated_at = time.time()

    # Calculate progress as percentage through stages
    try:
        idx = _STAGE_ORDER.index(stage)
        job.progress = int((idx / (len(_STAGE_ORDER) - 1)) * 100)
    except ValueError:
        pass

    logger.info(
        "[JobManager] job=%s → stage=%s (%d%%)",
        job_id, stage.value, job.progress,
    )


def complete_job(job_id: str, result: dict) -> None:
    """Mark a job as completed with its result."""
    job = _jobs.get(job_id)
    if not job:
        return
    job.stage = JobStage.COMPLETED
    job.stage_label = STAGE_LABELS[JobStage.COMPLETED]
    job.progress = 100
    job.result = result
    job.updated_at = time.time()
    logger.info("[JobManager] job=%s COMPLETED", job_id)


def fail_job(job_id: str, error: str, stage: str = "unknown") -> None:
    """Mark a job as failed."""
    job = _jobs.get(job_id)
    if not job:
        return
    job.stage = JobStage.FAILED
    job.stage_label = STAGE_LABELS[JobStage.FAILED]
    job.error = error
    job.error_stage = stage
    job.updated_at = time.time()
    logger.error("[JobManager] job=%s FAILED at %s: %s", job_id, stage, error)


def cancel_job(job_id: str) -> bool:
    """Cancel a running job. Returns True if cancelled."""
    job = _jobs.get(job_id)
    if not job:
        return False
    if job._task and not job._task.done():
        job._task.cancel()
        job.stage = JobStage.FAILED
        job.stage_label = "Cancelled"
        job.error = "Job was cancelled by user"
        job.updated_at = time.time()
        logger.info("[JobManager] job=%s CANCELLED", job_id)
        return True
    return False


def set_job_task(job_id: str, task: asyncio.Task) -> None:
    """Associate an asyncio.Task with a job for cancellation support."""
    job = _jobs.get(job_id)
    if job:
        job._task = task


def list_jobs(session_id: Optional[str] = None) -> list[dict]:
    """List all jobs, optionally filtered by session_id."""
    jobs = _jobs.values()
    if session_id:
        jobs = [j for j in jobs if j.session_id == session_id]
    return [j.to_dict() for j in sorted(jobs, key=lambda j: j.created_at, reverse=True)]
