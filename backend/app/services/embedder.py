"""
embedder.py — Chunk transcripts and generate embeddings using local SentenceTransformers.

Uses all-MiniLM-L6-v2 (384-dim, free, no API key needed).
All embeddings are generated locally on CPU — no network calls.
"""
from __future__ import annotations

import logging
import time

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.models.schemas import VideoMetadata
from app.services.embedder_model import embed_texts

logger = logging.getLogger(__name__)


def chunk_and_embed(
    transcript: str,
    metadata: VideoMetadata,
    session_id: str,
) -> list[dict]:
    """
    Split a transcript into overlapping chunks and generate embeddings for each.

    Embeddings are generated locally using SentenceTransformers (all-MiniLM-L6-v2).
    No external API calls are made.

    Args:
        transcript: The full transcript string for a single video.
        metadata:   VideoMetadata for this video (used to populate chunk metadata).
        session_id: The ingest session this video belongs to.

    Returns:
        A list of dicts, each containing:
            id          – Unique string identifier for the chunk.
            text        – The raw chunk text.
            embedding   – List[float] from all-MiniLM-L6-v2 (384-dim).
            metadata    – Dict of facets stored alongside the chunk in ChromaDB.

    Raises:
        RuntimeError: If chunking produces zero chunks.
    """
    logger.info("[Embedder] Starting chunk_and_embed for video=%s  session=%s", metadata.video_id, session_id)
    logger.info("[Embedder] Transcript length: %d chars", len(transcript))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50,
        length_function=len,
    )
    chunks: list[str] = splitter.split_text(transcript)

    logger.info("[Embedder] Splitter produced %d chunks", len(chunks))

    if not chunks:
        raise RuntimeError(
            f"RecursiveCharacterTextSplitter produced zero chunks for video "
            f"{metadata.video_id}. The transcript may be empty."
        )

    # ── Local embedding: SentenceTransformers (no API call) ──────────────
    logger.info("[Embedder] Generating local embeddings for %d chunks ...", len(chunks))
    embed_start = time.time()
    embeddings = embed_texts(chunks)
    logger.info(
        "[Embedder] Embeddings generated in %.2fs — %d vectors, dim=%d",
        time.time() - embed_start,
        len(embeddings),
        len(embeddings[0]) if embeddings else 0,
    )

    result_chunks: list[dict] = []

    for index, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
        chunk_id = f"{session_id}_video_{metadata.video_id}_chunk_{index}"

        result_chunks.append(
            {
                "id": chunk_id,
                "text": chunk_text,
                "embedding": embedding,
                "metadata": {
                    "video_id": metadata.video_id,
                    "session_id": session_id,
                    "chunk_index": index,
                    "creator": metadata.creator,
                    "engagement_rate": metadata.engagement_rate,
                    "views": metadata.views,
                    "likes": metadata.likes,
                    "comments": metadata.comments,
                    "follower_count": metadata.follower_count,
                    "upload_date": metadata.upload_date,
                    "duration_seconds": metadata.duration_seconds,
                    "source_url": metadata.url,
                },
            }
        )

    logger.info("[Embedder] Built %d chunk dicts for video=%s", len(result_chunks), metadata.video_id)

    return result_chunks
