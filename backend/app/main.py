from __future__ import annotations

import logging
import shutil
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# ---------------------------------------------------------------------------
# Logging configuration — ensure INFO-level messages are visible.
# Without this, Python's default root logger is at WARNING and all the
# pipeline instrumentation is silently discarded.
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stderr,
    force=True,          # override any pre-existing root handler
)

from app.core.config import settings
from app.api.routes.ingest import router as ingest_router
from app.api.routes.chat import router as chat_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.summary import router as summary_router

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (slowapi) — protects against abuse
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Social Media Video RAG Analyzer",
    description=(
        "A production-ready RAG API that ingests YouTube and Instagram video "
        "transcripts and answers analytical questions using Gemini 2.5 Flash."
    ),
    version="2.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# CORS — allow both localhost and 127.0.0.1 on port 3000
# ---------------------------------------------------------------------------

_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Also allow the configured FRONTEND_URL if it differs
if settings.FRONTEND_URL not in _ALLOWED_ORIGINS:
    _ALLOWED_ORIGINS.append(settings.FRONTEND_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Global exception handler — never return a bare 500 without context
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for any unhandled exception.  Returns a structured JSON body
    so the frontend always gets a parseable error instead of an HTML page.
    """
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "stage": "unknown",
            "error": "Internal server error",
            "details": f"{type(exc).__name__}: {exc}",
        },
    )

# ---------------------------------------------------------------------------
# Startup — pre-flight checks for required system tools
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup_checks():
    """Log whether critical system tools are available."""
    for tool in ("yt-dlp", "ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if path:
            logger.info("[Startup] ✓ %s found at %s", tool, path)
        else:
            logger.warning(
                "[Startup] ✗ %s NOT FOUND on PATH — Whisper fallback will fail. "
                "Install with: pip install yt-dlp  /  brew install ffmpeg",
                tool,
            )

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(ingest_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(jobs_router, prefix="/api")
app.include_router(feedback_router, prefix="/api")
app.include_router(summary_router, prefix="/api")

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Return a simple liveness signal with tool availability."""
    from app.services.vectorstore import vector_store
    chroma_ok = True
    try:
        vector_store._collection.count()
    except Exception:
        chroma_ok = False

    return {
        "status": "ok",
        "service": "ragbot-backend",
        "version": "2.0.0",
        "tools": {
            "yt-dlp": shutil.which("yt-dlp") is not None,
            "ffmpeg": shutil.which("ffmpeg") is not None,
            "ffprobe": shutil.which("ffprobe") is not None,
        },
        "chromadb": chroma_ok,
    }
