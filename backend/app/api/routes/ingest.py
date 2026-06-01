"""
ingest.py — Job-based video ingest endpoint.

POST /api/ingest now returns a job_id immediately (< 100ms) and runs the
full pipeline (metadata → transcript → chunk → embed → store) as an
asyncio background task. The frontend polls GET /api/jobs/{job_id} for
real-time progress updates.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
import traceback

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.models.schemas import (
    IngestRequest,
    IngestResponse,
    TranscriptResult,
    VideoMetadata,
)
from app.services.metadata import fetch_metadata
from app.services.transcript import fetch_youtube_transcript, fetch_instagram_transcript
from app.services.embedder import chunk_and_embed
from app.services.vectorstore import vector_store
from app.services.job_manager import (
    create_job,
    update_job_stage,
    complete_job,
    fail_job,
    set_job_task,
    JobStage,
)

# Shared in-memory session store (also imported by chat.py)
from app.api.routes import session_store

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Async wrappers (run blocking I/O in the default thread pool)
# ---------------------------------------------------------------------------

async def _fetch_metadata_async(url: str, video_id: str) -> VideoMetadata:
    """Run the blocking yt-dlp metadata call in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fetch_metadata, url, video_id)


async def _fetch_youtube_transcript_async(
    url: str,
    preferred_language: str | None,
) -> TranscriptResult:
    """Run the blocking YouTube transcript fetch in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, fetch_youtube_transcript, url, preferred_language
    )


async def _fetch_instagram_transcript_async(url: str) -> TranscriptResult:
    """Run the blocking Instagram/Whisper fetch in a thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fetch_instagram_transcript, url)


async def _chunk_and_embed_async(
    transcript_result: TranscriptResult,
    metadata: VideoMetadata,
    session_id: str,
) -> list[dict]:
    """Run the blocking chunk+embed in a thread pool."""
    loop = asyncio.get_running_loop()

    def _run() -> list[dict]:
        chunks = chunk_and_embed(
            transcript_result.transcript,
            metadata,
            session_id,
        )
        for chunk in chunks:
            chunk["metadata"]["transcript_language"] = transcript_result.info.language
            chunk["metadata"]["transcript_language_name"] = transcript_result.info.language_name
            chunk["metadata"]["transcript_source"] = transcript_result.info.source
            chunk["metadata"]["transcript_is_original"] = transcript_result.info.is_original
        return chunks

    return await loop.run_in_executor(None, _run)


# ---------------------------------------------------------------------------
# Pre-flight tool check
# ---------------------------------------------------------------------------

def _check_required_tools() -> dict[str, bool]:
    """Check whether yt-dlp, ffmpeg, ffprobe are on PATH."""
    tools = {}
    for name in ("yt-dlp", "ffmpeg", "ffprobe"):
        tools[name] = shutil.which(name) is not None
    return tools


# ---------------------------------------------------------------------------
# Background ingest pipeline
# ---------------------------------------------------------------------------

async def _run_ingest_pipeline(
    job_id: str,
    session_id: str,
    youtube_url: str,
    instagram_url: str,
    preferred_language: str | None,
) -> None:
    """
    Full ingest pipeline running as a background task.
    Updates job stages in real-time for frontend polling.
    """
    pipeline_start = time.time()

    try:
        # ── Stage: Validating ───────────────────────────────────────────
        update_job_stage(job_id, JobStage.VALIDATING)
        tools = _check_required_tools()
        logger.info("[Ingest:%s] Tool check: %s", job_id, tools)

        if not tools.get("yt-dlp"):
            fail_job(job_id, "yt-dlp is not installed or not on PATH", "validation")
            return

        if not tools.get("ffmpeg"):
            logger.warning("[Ingest:%s] ffmpeg NOT found — Whisper fallback will fail", job_id)

        # ── Stage: Fetching Metadata ────────────────────────────────────
        update_job_stage(job_id, JobStage.FETCHING_METADATA)
        try:
            meta_a, meta_b = await asyncio.gather(
                _fetch_metadata_async(youtube_url, "A"),
                _fetch_metadata_async(instagram_url, "B"),
                return_exceptions=True,
            )
        except Exception as exc:
            fail_job(job_id, f"Metadata fetch failed: {exc}", "metadata")
            return

        if isinstance(meta_a, BaseException):
            fail_job(job_id, f"YouTube metadata failed: {meta_a}", "metadata")
            return
        if isinstance(meta_b, BaseException):
            fail_job(job_id, f"Instagram metadata failed: {meta_b}", "metadata")
            return

        logger.info(
            "[Ingest:%s] Metadata OK — A: '%s' (%s views) B: '%s' (%s views)",
            job_id, meta_a.title[:40], meta_a.views, meta_b.title[:40], meta_b.views,
        )

        # ── Duration validation ─────────────────────────────────────────
        max_dur = settings.MAX_VIDEO_DURATION_SECONDS
        for label, meta in [("A (YouTube)", meta_a), ("B (Instagram)", meta_b)]:
            if meta.duration_seconds > max_dur:
                fail_job(
                    job_id,
                    f"Video {label} is {meta.duration_seconds // 60} min — max is {max_dur // 60} min",
                    "validation",
                )
                return

        # ── Stage: Downloading Audio / Transcribing ─────────────────────
        update_job_stage(job_id, JobStage.DOWNLOADING_AUDIO)

        # YouTube transcript uses captions API (no audio download needed usually)
        # Instagram requires yt-dlp audio download → Whisper
        update_job_stage(job_id, JobStage.TRANSCRIBING)
        try:
            result_a, result_b = await asyncio.gather(
                _fetch_youtube_transcript_async(youtube_url, preferred_language),
                _fetch_instagram_transcript_async(instagram_url),
                return_exceptions=True,
            )
        except Exception as exc:
            fail_job(job_id, f"Transcript fetch failed: {exc}", "transcript")
            return

        if isinstance(result_a, BaseException):
            fail_job(job_id, f"YouTube transcript failed: {result_a}", "youtube_transcript")
            return
        if isinstance(result_b, BaseException):
            fail_job(job_id, f"Instagram transcript failed: {result_b}", "instagram_transcript")
            return

        logger.info(
            "[Ingest:%s] Transcripts OK — A: %s/%s/%d chars  B: %s/%s/%d chars",
            job_id,
            result_a.info.source, result_a.info.language, len(result_a.transcript),
            result_b.info.source, result_b.info.language, len(result_b.transcript),
        )

        # ── Stage: Chunking ─────────────────────────────────────────────
        update_job_stage(job_id, JobStage.CHUNKING)
        await asyncio.sleep(0)  # yield to event loop

        # ── Stage: Embedding ────────────────────────────────────────────
        update_job_stage(job_id, JobStage.EMBEDDING)
        try:
            chunks_a, chunks_b = await asyncio.gather(
                _chunk_and_embed_async(result_a, meta_a, session_id),
                _chunk_and_embed_async(result_b, meta_b, session_id),
                return_exceptions=True,
            )
        except Exception as exc:
            fail_job(job_id, f"Embedding failed: {exc}", "embedding")
            return

        if isinstance(chunks_a, BaseException):
            fail_job(job_id, f"YouTube embedding failed: {chunks_a}", "embedding")
            return
        if isinstance(chunks_b, BaseException):
            fail_job(job_id, f"Instagram embedding failed: {chunks_b}", "embedding")
            return

        logger.info(
            "[Ingest:%s] Embedding OK — A: %d chunks  B: %d chunks",
            job_id, len(chunks_a), len(chunks_b),
        )

        # ── Stage: Storing ──────────────────────────────────────────────
        update_job_stage(job_id, JobStage.STORING)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, vector_store.upsert, chunks_a + chunks_b)
        except Exception as exc:
            fail_job(job_id, f"Vector store upsert failed: {exc}", "vectorstore")
            return

        # ── Cache session metadata for chat ─────────────────────────────
        session_store[session_id] = {"A": meta_a, "B": meta_b}

        # ── Complete! ───────────────────────────────────────────────────
        result = {
            "session_id": session_id,
            "video_a": meta_a.model_dump(),
            "video_b": meta_b.model_dump(),
            "status": "ready",
            "transcript_a_info": result_a.info.model_dump(),
            "transcript_b_info": result_b.info.model_dump(),
        }
        complete_job(job_id, result)

        logger.info(
            "[Ingest:%s] Pipeline COMPLETE in %.1fs — session=%s",
            job_id, time.time() - pipeline_start, session_id,
        )

    except asyncio.CancelledError:
        logger.info("[Ingest:%s] Job cancelled", job_id)
        fail_job(job_id, "Job was cancelled", "cancelled")
    except Exception as exc:
        logger.exception("[Ingest:%s] Unexpected error", job_id)
        fail_job(job_id, str(exc), "unknown")


# ---------------------------------------------------------------------------
# Ingest endpoint — returns job_id immediately
# ---------------------------------------------------------------------------

@router.post("/ingest")
async def ingest(request: IngestRequest) -> dict:
    """
    Start a video ingest job.

    Returns a job_id immediately. The full pipeline runs as a background task.
    Poll GET /api/jobs/{job_id} for progress updates.

    Response:
        { "job_id": "job_abc123", "session_id": "...", "status": "accepted" }
    """
    logger.info(
        "[Ingest] New request — youtube=%s instagram=%s session=%s lang=%s",
        request.youtube_url,
        request.instagram_url,
        request.session_id,
        request.preferred_language or "auto",
    )

    # Create job
    job = create_job(
        session_id=request.session_id,
        youtube_url=request.youtube_url,
        instagram_url=request.instagram_url,
        preferred_language=request.preferred_language,
    )

    # Launch background task
    task = asyncio.create_task(
        _run_ingest_pipeline(
            job_id=job.job_id,
            session_id=request.session_id,
            youtube_url=request.youtube_url,
            instagram_url=request.instagram_url,
            preferred_language=request.preferred_language,
        )
    )
    set_job_task(job.job_id, task)

    return {
        "job_id": job.job_id,
        "session_id": request.session_id,
        "status": "accepted",
    }

