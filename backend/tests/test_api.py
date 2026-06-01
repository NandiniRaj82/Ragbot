"""
Tests for API endpoint smoke tests.

Uses FastAPI's TestClient for synchronous endpoint testing
without needing external services (Gemini, ChromaDB, etc.).
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "ragbot-backend"
        assert "tools" in data
        assert "chromadb" in data

    def test_health_contains_version(self):
        response = client.get("/health")
        data = response.json()
        assert "version" in data


# ---------------------------------------------------------------------------
# Ingest endpoint
# ---------------------------------------------------------------------------

class TestIngestEndpoint:
    def test_ingest_rejects_invalid_youtube_url(self):
        response = client.post("/api/ingest", json={
            "youtube_url": "https://vimeo.com/123",
            "instagram_url": "https://www.instagram.com/reel/abc/",
            "session_id": "test_session",
        })
        assert response.status_code == 422

    def test_ingest_rejects_invalid_instagram_url(self):
        response = client.post("/api/ingest", json={
            "youtube_url": "https://www.youtube.com/watch?v=abc",
            "instagram_url": "https://tiktok.com/video/123",
            "session_id": "test_session",
        })
        assert response.status_code == 422

    def test_ingest_rejects_empty_session_id(self):
        response = client.post("/api/ingest", json={
            "youtube_url": "https://www.youtube.com/watch?v=abc",
            "instagram_url": "https://www.instagram.com/reel/abc/",
            "session_id": "   ",
        })
        assert response.status_code == 422

    def test_ingest_accepts_valid_request(self):
        response = client.post("/api/ingest", json={
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "instagram_url": "https://www.instagram.com/reel/abc123/",
            "session_id": "test_session_001",
        })
        assert response.status_code == 200
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "accepted"
        assert data["session_id"] == "test_session_001"


# ---------------------------------------------------------------------------
# Jobs endpoint
# ---------------------------------------------------------------------------

class TestJobsEndpoint:
    def test_get_nonexistent_job(self):
        response = client.get("/api/jobs/job_nonexistent_abc")
        assert response.status_code == 404

    def test_get_existing_job(self):
        # First create a job via ingest
        ingest_resp = client.post("/api/ingest", json={
            "youtube_url": "https://www.youtube.com/watch?v=test123",
            "instagram_url": "https://www.instagram.com/reel/test123/",
            "session_id": "test_session",
        })
        job_id = ingest_resp.json()["job_id"]

        # Now poll it
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert "stage" in data
        assert "progress" in data

    def test_cancel_nonexistent_job(self):
        response = client.delete("/api/jobs/job_nonexistent_abc")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Chat endpoint
# ---------------------------------------------------------------------------

class TestChatEndpoint:
    def test_chat_rejects_empty_query(self):
        response = client.post("/api/chat", json={
            "query": "   ",
            "session_id": "test",
        })
        assert response.status_code == 422

    def test_chat_rejects_unknown_session(self):
        response = client.post("/api/chat", json={
            "query": "What is Video A about?",
            "session_id": "nonexistent_session",
        })
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Feedback endpoint
# ---------------------------------------------------------------------------

class TestFeedbackEndpoint:
    def test_submit_valid_feedback(self):
        response = client.post("/api/feedback", json={
            "session_id": "s1",
            "message_id": "msg_001",
            "rating": "up",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "recorded"
        assert data["rating"] == "up"

    def test_submit_feedback_with_comment(self):
        response = client.post("/api/feedback", json={
            "session_id": "s1",
            "message_id": "msg_002",
            "rating": "down",
            "comment": "Response was too generic",
        })
        assert response.status_code == 200
        assert response.json()["rating"] == "down"

    def test_feedback_rejects_invalid_rating(self):
        response = client.post("/api/feedback", json={
            "session_id": "s1",
            "message_id": "msg_001",
            "rating": "neutral",
        })
        assert response.status_code == 422

    def test_feedback_stats(self):
        # Submit some feedback
        client.post("/api/feedback", json={
            "session_id": "stats_test",
            "message_id": "m1",
            "rating": "up",
        })
        client.post("/api/feedback", json={
            "session_id": "stats_test",
            "message_id": "m2",
            "rating": "up",
        })
        client.post("/api/feedback", json={
            "session_id": "stats_test",
            "message_id": "m3",
            "rating": "down",
        })

        response = client.get("/api/feedback/stats/stats_test")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["thumbs_up"] == 2
        assert data["thumbs_down"] == 1

    def test_global_feedback_stats(self):
        response = client.get("/api/feedback/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "satisfaction_rate" in data


# ---------------------------------------------------------------------------
# Summary endpoint
# ---------------------------------------------------------------------------

class TestSummaryEndpoint:
    def test_summary_rejects_missing_session(self):
        response = client.post("/api/summary", json={
            "session_id": "nonexistent_session",
        })
        assert response.status_code == 404

    def test_summary_rejects_empty_session(self):
        response = client.post("/api/summary", json={
            "session_id": "",
        })
        assert response.status_code == 422
