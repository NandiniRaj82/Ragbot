from __future__ import annotations

import re
from typing import Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    youtube_url: str
    instagram_url: str
    session_id: str
    preferred_language: Optional[str] = Field(
        default=None,
        description=(
            "BCP-47 language code to prefer when selecting a YouTube transcript "
            "(e.g. 'en', 'hi', 'te', 'ta', 'fr', 'de', 'ja').  When None the "
            "best available language is chosen automatically."
        ),
    )

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(
            r"^https?://(www\.|m\.)?(youtube\.com|youtu\.be)/",
            v, re.IGNORECASE,
        ):
            raise ValueError(
                "Must be a valid YouTube URL (e.g. https://www.youtube.com/watch?v=...)"
            )
        return v

    @field_validator("instagram_url")
    @classmethod
    def validate_instagram_url(cls, v: str) -> str:
        v = v.strip()
        if not re.match(
            r"^https?://(www\.)?instagram\.com/",
            v, re.IGNORECASE,
        ):
            raise ValueError(
                "Must be a valid Instagram URL (e.g. https://www.instagram.com/reel/...)"
            )
        return v

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("session_id must not be empty")
        if len(v) > 200:
            raise ValueError("session_id is too long (max 200 characters)")
        return v


class VideoMetadata(BaseModel):
    video_id: str  # "A" or "B"
    url: str
    title: str
    creator: str
    follower_count: int
    views: int
    likes: int
    comments: int
    engagement_rate: float
    hashtags: list[str]
    upload_date: str
    duration_seconds: int
    thumbnail_url: str


class IngestResponse(BaseModel):
    session_id: str
    video_a: VideoMetadata
    video_b: VideoMetadata
    status: str
    # Transcript provenance surfaced to the caller for transparency
    transcript_a_info: Optional[TranscriptInfo] = None
    transcript_b_info: Optional[TranscriptInfo] = None


# ---------------------------------------------------------------------------
# Transcript result (returned by the transcript service, stored in chunks)
# ---------------------------------------------------------------------------

TranscriptSource = Literal["manual", "auto-generated", "translated", "whisper"]


class TranscriptInfo(BaseModel):
    """Metadata about how a transcript was obtained."""
    language: str        # BCP-47 code, e.g. "en", "hi", "te"
    language_name: str   # Human-readable, e.g. "English", "Hindi"
    source: TranscriptSource
    is_original: bool    # False when the text is a translation
    video_id_yt: str     # YouTube video ID (for logging / audit)


class TranscriptResult(BaseModel):
    """Full result object returned by fetch_youtube_transcript."""
    transcript: str
    info: TranscriptInfo


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    session_id: str

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Query must not be empty")
        return v

    @field_validator("session_id")
    @classmethod
    def validate_chat_session_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("session_id must not be empty")
        return v


class SourceCitation(BaseModel):
    video_id: str        # "A" or "B"
    chunk_index: int
    chunk_text: str


class RAGMetrics(BaseModel):
    """Evaluation metrics for a single RAG retrieval + generation cycle."""
    avg_similarity: float = Field(
        ..., description="Average cosine similarity of retrieved chunks (0–1)"
    )
    top_similarity: float = Field(
        ..., description="Highest cosine similarity among retrieved chunks"
    )
    lowest_similarity: float = Field(
        ..., description="Lowest cosine similarity among retrieved chunks"
    )
    num_chunks_used: int = Field(
        ..., description="Total number of chunks retrieved"
    )
    video_a_chunks: int = Field(
        ..., description="Chunks sourced from Video A"
    )
    video_b_chunks: int = Field(
        ..., description="Chunks sourced from Video B"
    )
    retrieval_time_ms: float = Field(
        ..., description="Time taken for embedding + retrieval in milliseconds"
    )
    generation_time_ms: float = Field(
        ..., description="Time taken for LLM generation in milliseconds"
    )


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

class FeedbackRequest(BaseModel):
    """User feedback on an individual chat response."""
    session_id: str
    message_id: str
    rating: Literal["up", "down"]
    comment: Optional[str] = Field(
        default=None, max_length=1000,
        description="Optional free-text feedback from the user",
    )

    @field_validator("session_id")
    @classmethod
    def validate_fb_session_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("session_id must not be empty")
        return v

    @field_validator("message_id")
    @classmethod
    def validate_fb_message_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message_id must not be empty")
        return v


# Resolve forward reference (IngestResponse references TranscriptInfo
# which is defined after it above — we rebuild the model to update refs)
IngestResponse.model_rebuild()
