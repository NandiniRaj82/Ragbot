"""
feedback.py — User feedback on RAG chat responses.

POST /api/feedback  — Submit thumbs-up/down rating for a message
GET  /api/feedback/stats/{session_id} — Get aggregated feedback stats
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.models.schemas import FeedbackRequest

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory feedback store (bounded LRU)
# In production, replace with a database.
# ---------------------------------------------------------------------------

_MAX_FEEDBACK_ENTRIES = 5000


class _FeedbackStore:
    """Thread-safe bounded feedback store keyed by (session_id, message_id)."""

    def __init__(self, max_size: int = _MAX_FEEDBACK_ENTRIES) -> None:
        self._store: OrderedDict[str, dict] = OrderedDict()
        self._max_size = max_size

    def add(self, entry: dict) -> None:
        key = f"{entry['session_id']}:{entry['message_id']}"
        self._store[key] = entry
        self._store.move_to_end(key)
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def get_session_stats(self, session_id: str) -> dict:
        entries = [v for v in self._store.values() if v["session_id"] == session_id]
        up = sum(1 for e in entries if e["rating"] == "up")
        down = sum(1 for e in entries if e["rating"] == "down")
        return {
            "session_id": session_id,
            "total": len(entries),
            "thumbs_up": up,
            "thumbs_down": down,
            "satisfaction_rate": round(up / len(entries) * 100, 1) if entries else 0,
        }

    def get_all_stats(self) -> dict:
        total = len(self._store)
        up = sum(1 for e in self._store.values() if e["rating"] == "up")
        down = sum(1 for e in self._store.values() if e["rating"] == "down")
        return {
            "total": total,
            "thumbs_up": up,
            "thumbs_down": down,
            "satisfaction_rate": round(up / total * 100, 1) if total else 0,
        }


_feedback_store = _FeedbackStore()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict:
    """
    Submit user feedback (thumbs-up or thumbs-down) for a chat response.

    This data can be used for RLHF-style quality improvement loops.
    """
    entry = {
        "session_id": request.session_id,
        "message_id": request.message_id,
        "rating": request.rating,
        "comment": request.comment,
        "timestamp": time.time(),
    }
    _feedback_store.add(entry)

    logger.info(
        "[Feedback] %s for session=%s message=%s%s",
        "👍" if request.rating == "up" else "👎",
        request.session_id,
        request.message_id,
        f" comment='{request.comment[:50]}'" if request.comment else "",
    )

    return {"status": "recorded", "rating": request.rating}


@router.get("/feedback/stats/{session_id}")
async def get_feedback_stats(session_id: str) -> dict:
    """Get aggregated feedback statistics for a session."""
    return _feedback_store.get_session_stats(session_id)


@router.get("/feedback/stats")
async def get_global_feedback_stats() -> dict:
    """Get global feedback statistics across all sessions."""
    return _feedback_store.get_all_stats()
