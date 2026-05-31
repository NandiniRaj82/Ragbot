"""
embedder_model.py — Thread-safe singleton for the SentenceTransformer embedding model.

Uses `all-MiniLM-L6-v2` (22 MB, 384-dim, free, runs locally on CPU).
The model is loaded once on first use and cached for the process lifetime.
"""
from __future__ import annotations

import logging
import threading
import time

from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None
_lock = threading.Lock()

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # output dimension for this model


def _get_model() -> SentenceTransformer:
    """Return the cached SentenceTransformer (created once, reused)."""
    global _model
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        logger.info("[EmbedModel] Loading '%s' ...", MODEL_NAME)
        start = time.time()
        _model = SentenceTransformer(MODEL_NAME)
        logger.info(
            "[EmbedModel] Model loaded in %.2fs  dim=%d",
            time.time() - start,
            EMBEDDING_DIM,
        )
        return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts.

    Returns:
        List of float vectors, one per input text.
        Each vector has EMBEDDING_DIM dimensions.
    """
    model = _get_model()
    logger.info("[EmbedModel] Encoding %d texts ...", len(texts))
    start = time.time()
    embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
    logger.info(
        "[EmbedModel] Encoded %d texts in %.2fs",
        len(texts),
        time.time() - start,
    )
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Embed a single query string. Returns a single float vector."""
    model = _get_model()
    embedding = model.encode(query, show_progress_bar=False, convert_to_numpy=True)
    return embedding.tolist()
