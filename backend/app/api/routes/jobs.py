"""
jobs.py — Job status and management endpoints.

GET  /api/jobs/{job_id}  — Poll job status (used by frontend for progress UI)
DELETE /api/jobs/{job_id} — Cancel a running job
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services.job_manager import get_job, cancel_job

router = APIRouter()


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> dict:
    """
    Poll the status of an ingest job.

    Returns the current stage, progress percentage, and result (when completed).
    Frontend should poll this every 1-2 seconds during processing.
    """
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job.to_dict()


@router.delete("/jobs/{job_id}")
async def cancel_job_endpoint(job_id: str) -> dict:
    """Cancel a running ingest job."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    cancelled = cancel_job(job_id)
    if not cancelled:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is not running (status: {job.stage.value})"
        )
    return {"job_id": job_id, "status": "cancelled"}
