"""
Tests for Pydantic request/response schemas.

Validates URL patterns, field constraints, and edge cases
that a production API should handle gracefully.
"""
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    IngestRequest,
    ChatRequest,
    FeedbackRequest,
    VideoMetadata,
    RAGMetrics,
    SourceCitation,
    TranscriptInfo,
)


# ---------------------------------------------------------------------------
# IngestRequest validation
# ---------------------------------------------------------------------------

class TestIngestRequest:
    """Test URL validation and field constraints."""

    def test_valid_request(self):
        req = IngestRequest(
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            instagram_url="https://www.instagram.com/reel/abc123/",
            session_id="session_001",
        )
        assert req.youtube_url.startswith("https://")
        assert req.session_id == "session_001"
        assert req.preferred_language is None

    def test_valid_with_language(self):
        req = IngestRequest(
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            instagram_url="https://www.instagram.com/reel/abc123/",
            session_id="session_001",
            preferred_language="hi",
        )
        assert req.preferred_language == "hi"

    def test_invalid_youtube_url(self):
        with pytest.raises(ValidationError, match="YouTube URL"):
            IngestRequest(
                youtube_url="https://vimeo.com/123456",
                instagram_url="https://www.instagram.com/reel/abc/",
                session_id="session_001",
            )

    def test_invalid_instagram_url(self):
        with pytest.raises(ValidationError, match="Instagram URL"):
            IngestRequest(
                youtube_url="https://www.youtube.com/watch?v=abc",
                instagram_url="https://tiktok.com/@user/video/123",
                session_id="session_001",
            )

    def test_empty_session_id(self):
        with pytest.raises(ValidationError, match="session_id"):
            IngestRequest(
                youtube_url="https://www.youtube.com/watch?v=abc",
                instagram_url="https://www.instagram.com/reel/abc/",
                session_id="   ",
            )

    def test_session_id_too_long(self):
        with pytest.raises(ValidationError, match="too long"):
            IngestRequest(
                youtube_url="https://www.youtube.com/watch?v=abc",
                instagram_url="https://www.instagram.com/reel/abc/",
                session_id="x" * 201,
            )

    def test_youtu_be_short_url(self):
        req = IngestRequest(
            youtube_url="https://youtu.be/dQw4w9WgXcQ",
            instagram_url="https://www.instagram.com/reel/abc/",
            session_id="s1",
        )
        assert "youtu.be" in req.youtube_url

    def test_mobile_youtube_url(self):
        req = IngestRequest(
            youtube_url="https://m.youtube.com/watch?v=dQw4w9WgXcQ",
            instagram_url="https://www.instagram.com/reel/abc/",
            session_id="s1",
        )
        assert req.youtube_url.startswith("https://m.youtube.com")

    def test_strips_whitespace(self):
        req = IngestRequest(
            youtube_url="  https://www.youtube.com/watch?v=abc  ",
            instagram_url="  https://www.instagram.com/reel/abc/  ",
            session_id="  session_001  ",
        )
        assert not req.session_id.startswith(" ")


# ---------------------------------------------------------------------------
# ChatRequest validation
# ---------------------------------------------------------------------------

class TestChatRequest:
    """Test chat query constraints."""

    def test_valid_request(self):
        req = ChatRequest(query="Why did Video A get more views?", session_id="s1")
        assert req.query == "Why did Video A get more views?"

    def test_empty_query(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="   ", session_id="s1")

    def test_query_too_long(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="a" * 4001, session_id="s1")

    def test_empty_session_id(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="test", session_id="   ")


# ---------------------------------------------------------------------------
# FeedbackRequest validation
# ---------------------------------------------------------------------------

class TestFeedbackRequest:
    """Test feedback model constraints."""

    def test_valid_thumbs_up(self):
        req = FeedbackRequest(
            session_id="s1", message_id="msg_001", rating="up"
        )
        assert req.rating == "up"
        assert req.comment is None

    def test_valid_thumbs_down_with_comment(self):
        req = FeedbackRequest(
            session_id="s1",
            message_id="msg_001",
            rating="down",
            comment="Response was too vague",
        )
        assert req.rating == "down"
        assert req.comment == "Response was too vague"

    def test_invalid_rating(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(
                session_id="s1", message_id="msg_001", rating="neutral"
            )

    def test_empty_session_id(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(
                session_id="  ", message_id="msg_001", rating="up"
            )

    def test_empty_message_id(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(
                session_id="s1", message_id="  ", rating="up"
            )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class TestRAGMetrics:
    """Test RAG metrics model construction."""

    def test_valid_metrics(self):
        metrics = RAGMetrics(
            avg_similarity=0.8542,
            top_similarity=0.9231,
            lowest_similarity=0.7123,
            num_chunks_used=6,
            video_a_chunks=3,
            video_b_chunks=3,
            retrieval_time_ms=12.5,
            generation_time_ms=2340.0,
        )
        assert metrics.avg_similarity == 0.8542
        assert metrics.num_chunks_used == 6
        assert metrics.video_a_chunks + metrics.video_b_chunks == 6

    def test_serialization(self):
        metrics = RAGMetrics(
            avg_similarity=0.85,
            top_similarity=0.92,
            lowest_similarity=0.71,
            num_chunks_used=4,
            video_a_chunks=2,
            video_b_chunks=2,
            retrieval_time_ms=10.0,
            generation_time_ms=2000.0,
        )
        data = metrics.model_dump()
        assert isinstance(data, dict)
        assert "avg_similarity" in data
        assert "generation_time_ms" in data


class TestVideoMetadata:
    """Test video metadata model."""

    def test_engagement_rate_calculation(self):
        vm = VideoMetadata(
            video_id="A",
            url="https://youtube.com/watch?v=abc",
            title="Test Video",
            creator="Test Creator",
            follower_count=10000,
            views=50000,
            likes=2500,
            comments=300,
            engagement_rate=5.6,
            hashtags=["test", "video"],
            upload_date="2024-01-01",
            duration_seconds=300,
            thumbnail_url="https://img.youtube.com/thumb.jpg",
        )
        assert vm.video_id == "A"
        assert vm.views == 50000
        assert len(vm.hashtags) == 2
