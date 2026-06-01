"""
summary.py — Auto-generated comparison summary after video ingest.

POST /api/summary  — Generate a one-shot executive summary comparing both videos.
                     Returns a streaming SSE response for real-time display.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from google import genai
from google.genai import types as genai_types

from app.core.config import settings
from app.api.routes import session_store
from app.services.vectorstore import vector_store
from app.services.embedder_model import embed_query

logger = logging.getLogger(__name__)
router = APIRouter()

GEMINI_MODEL = "gemini-2.5-flash"

# Singleton Gemini client (reuse from rag_chain if available)
_gemini_client: genai.Client | None = None


def _get_gemini_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _gemini_client


SUMMARY_PROMPT = """\
You are a social media analytics expert. Analyze the two videos below and generate a concise, \
data-driven executive summary comparing them.

Video A: {meta_a}
Video B: {meta_b}

Transcript excerpts from Video A:
{excerpts_a}

Transcript excerpts from Video B:
{excerpts_b}

Generate a summary with these sections (use markdown formatting):
## 📊 Key Metrics Comparison
A brief bullet-point comparison of views, likes, engagement rate, and duration.

## 🎯 Content Analysis
What each video is about, based on the transcript excerpts. 2-3 sentences each.

## 🏆 Winner & Why
Which video performs better and a clear, data-backed reason why.

## 💡 Actionable Recommendations
2-3 specific, actionable tips for the content creator to improve their next video.

Keep the entire summary under 400 words. Be specific and cite numbers.\
"""


def _format_metadata(meta) -> str:
    """Format VideoMetadata into a concise string."""
    return (
        f"title='{meta.title}', creator='{meta.creator}', "
        f"views={meta.views:,}, likes={meta.likes:,}, comments={meta.comments:,}, "
        f"engagement_rate={meta.engagement_rate:.4f}%, "
        f"duration={meta.duration_seconds}s, uploaded={meta.upload_date}"
    )


async def _stream_summary(session_id: str, video_metadata: dict) -> AsyncGenerator[str, None]:
    """Stream a comparison summary using Gemini."""
    loop = asyncio.get_running_loop()
    meta_a = video_metadata.get("A")
    meta_b = video_metadata.get("B")

    # Retrieve some transcript chunks for context
    def _get_excerpts():
        # Get representative chunks from each video
        query_embedding = embed_query("summarize video content and engagement")
        all_docs = vector_store.query(
            query_embedding=query_embedding,
            session_id=session_id,
            n_results=6,
        )
        excerpts_a = []
        excerpts_b = []
        for doc in all_docs:
            vid_id = doc.get("metadata", {}).get("video_id", "?")
            text = doc.get("document", "")[:300]
            if vid_id == "A":
                excerpts_a.append(text)
            else:
                excerpts_b.append(text)
        return excerpts_a, excerpts_b

    excerpts_a, excerpts_b = await loop.run_in_executor(None, _get_excerpts)

    prompt = SUMMARY_PROMPT.format(
        meta_a=_format_metadata(meta_a),
        meta_b=_format_metadata(meta_b),
        excerpts_a="\n".join(f"- {e}" for e in excerpts_a) or "No excerpts available",
        excerpts_b="\n".join(f"- {e}" for e in excerpts_b) or "No excerpts available",
    )

    token_queue: asyncio.Queue[str | None] = asyncio.Queue()

    def _stream_to_queue():
        try:
            client = _get_gemini_client()
            stream = client.models.generate_content_stream(
                model=GEMINI_MODEL,
                contents=[genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=prompt)],
                )],
                config=genai_types.GenerateContentConfig(
                    temperature=0.4,
                    max_output_tokens=2048,
                ),
            )
            for chunk in stream:
                if chunk.text:
                    loop.call_soon_threadsafe(token_queue.put_nowait, chunk.text)
        except Exception as exc:
            error_msg = f"\n\n⚠️ Summary generation error: {exc}"
            loop.call_soon_threadsafe(token_queue.put_nowait, error_msg)
        finally:
            loop.call_soon_threadsafe(token_queue.put_nowait, None)

    stream_future = loop.run_in_executor(None, _stream_to_queue)

    try:
        while True:
            token = await token_queue.get()
            if token is None:
                break
            payload = json.dumps({"token": token}, ensure_ascii=False)
            yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        return

    await stream_future

    yield f"data: {json.dumps({'done': True})}\n\n"


@router.post("/summary")
async def generate_summary(request: dict) -> StreamingResponse:
    """
    Generate an AI-powered executive summary comparing both ingested videos.

    Streams the summary token-by-token via SSE, similar to the chat endpoint.
    Call this after ingest completes for instant insights without typing a question.
    """
    session_id = request.get("session_id", "")
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    video_metadata = session_store.get(session_id)
    if video_metadata is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{session_id}' not found. Run ingest first.",
        )

    return StreamingResponse(
        _stream_summary(session_id, video_metadata),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
