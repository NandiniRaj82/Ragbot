from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.schemas import ChatRequest, SourceCitation
from app.services.rag_chain import astream_rag
from app.api.routes import session_store

router = APIRouter()


async def _event_stream(
    query: str,
    session_id: str,
    video_metadata: dict,
) -> AsyncGenerator[str, None]:
    """
    Async generator that converts astream_rag output into SSE-formatted strings.

    Yields:
        SSE-formatted lines: one per token plus one final "done" event.
    """
    try:
        async for item in astream_rag(query, session_id, video_metadata):
            if isinstance(item, str):
                payload = json.dumps({"token": item}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
            elif isinstance(item, list):
                # Final citations — item is list[SourceCitation]
                serialized = [
                    {
                        "video_id": c.video_id,
                        "chunk_index": c.chunk_index,
                        "chunk_text": c.chunk_text,
                    }
                    for c in item
                ]
                payload = json.dumps({"done": True, "sources": serialized})
                yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        # Client disconnected — stop yielding cleanly
        return
    except RuntimeError as exc:
        error_payload = json.dumps({"error": str(exc)})
        yield f"data: {error_payload}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """
    Stream an LLM response for a RAG query over a given session.

    Returns SSE events:
        data: {"token": "..."}\\n\\n        — one per streamed token
        data: {"done": true, "sources": [...]}\\n\\n  — final event with citations
        data: {"error": "..."}\\n\\n        — on error
    """
    if not request.query.strip():
        raise HTTPException(status_code=422, detail="Query must not be empty.")

    video_metadata = session_store.get(request.session_id)
    if video_metadata is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Session '{request.session_id}' not found. "
                "Please call POST /api/ingest first."
            ),
        )

    return StreamingResponse(
        _event_stream(request.query, request.session_id, video_metadata),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
