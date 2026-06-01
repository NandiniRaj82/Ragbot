"""
Tests for the in-process job manager.

Validates the complete job lifecycle: create → stage transitions →
complete/fail/cancel, including edge cases like eviction and
progress calculation.
"""
import asyncio
import pytest

from app.services.job_manager import (
    create_job,
    get_job,
    update_job_stage,
    complete_job,
    fail_job,
    cancel_job,
    set_job_task,
    list_jobs,
    JobStage,
    STAGE_LABELS,
    _jobs,
)


@pytest.fixture(autouse=True)
def _clean_jobs():
    """Clear the global job store before each test."""
    _jobs.clear()
    yield
    _jobs.clear()


# ---------------------------------------------------------------------------
# Job creation
# ---------------------------------------------------------------------------

class TestJobCreation:
    def test_create_job_returns_state(self):
        job = create_job("s1", "https://youtube.com/v=abc", "https://instagram.com/reel/x")
        assert job.job_id.startswith("job_")
        assert job.session_id == "s1"
        assert job.stage == JobStage.PENDING
        assert job.progress == 0
        assert job.error is None

    def test_created_job_is_retrievable(self):
        job = create_job("s1", "yt_url", "ig_url")
        retrieved = get_job(job.job_id)
        assert retrieved is not None
        assert retrieved.job_id == job.job_id

    def test_nonexistent_job_returns_none(self):
        assert get_job("job_nonexistent") is None

    def test_job_id_uniqueness(self):
        job1 = create_job("s1", "yt", "ig")
        job2 = create_job("s1", "yt", "ig")
        assert job1.job_id != job2.job_id

    def test_preferred_language_stored(self):
        job = create_job("s1", "yt", "ig", preferred_language="hi")
        assert job.preferred_language == "hi"


# ---------------------------------------------------------------------------
# Stage transitions
# ---------------------------------------------------------------------------

class TestStageTransitions:
    def test_update_stage(self):
        job = create_job("s1", "yt", "ig")
        update_job_stage(job.job_id, JobStage.VALIDATING)
        updated = get_job(job.job_id)
        assert updated.stage == JobStage.VALIDATING
        assert updated.stage_label == "Validating URLs"

    def test_progress_calculation(self):
        job = create_job("s1", "yt", "ig")
        # Pending = 0%
        assert job.progress == 0

        update_job_stage(job.job_id, JobStage.FETCHING_METADATA)
        assert get_job(job.job_id).progress > 0

        update_job_stage(job.job_id, JobStage.EMBEDDING)
        progress_at_embedding = get_job(job.job_id).progress
        assert 50 < progress_at_embedding < 100

    def test_completed_is_100_percent(self):
        job = create_job("s1", "yt", "ig")
        complete_job(job.job_id, {"result": "test"})
        completed = get_job(job.job_id)
        assert completed.progress == 100
        assert completed.stage == JobStage.COMPLETED

    def test_all_stages_have_labels(self):
        for stage in JobStage:
            assert stage in STAGE_LABELS


# ---------------------------------------------------------------------------
# Job completion and failure
# ---------------------------------------------------------------------------

class TestJobCompletion:
    def test_complete_job_stores_result(self):
        job = create_job("s1", "yt", "ig")
        result = {"session_id": "s1", "status": "ready"}
        complete_job(job.job_id, result)
        completed = get_job(job.job_id)
        assert completed.result == result
        assert completed.stage == JobStage.COMPLETED
        assert completed.stage_label == "Ready to chat"

    def test_fail_job(self):
        job = create_job("s1", "yt", "ig")
        fail_job(job.job_id, "Something went wrong", "transcript")
        failed = get_job(job.job_id)
        assert failed.stage == JobStage.FAILED
        assert failed.error == "Something went wrong"
        assert failed.error_stage == "transcript"

    def test_complete_nonexistent_job_is_noop(self):
        complete_job("job_nonexistent", {"data": "test"})  # should not raise

    def test_fail_nonexistent_job_is_noop(self):
        fail_job("job_nonexistent", "error", "stage")  # should not raise


# ---------------------------------------------------------------------------
# Job cancellation
# ---------------------------------------------------------------------------

class TestJobCancellation:
    def test_cancel_without_task_returns_false(self):
        job = create_job("s1", "yt", "ig")
        result = cancel_job(job.job_id)
        assert result is False

    def test_cancel_nonexistent_returns_false(self):
        assert cancel_job("job_nonexistent") is False

    def test_cancel_with_task(self):
        job = create_job("s1", "yt", "ig")

        async def _dummy():
            await asyncio.sleep(100)

        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(_dummy())
            set_job_task(job.job_id, task)
            result = cancel_job(job.job_id)
            assert result is True
            assert get_job(job.job_id).stage == JobStage.FAILED
            assert "cancelled" in get_job(job.job_id).stage_label.lower()
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# Job serialization
# ---------------------------------------------------------------------------

class TestJobSerialization:
    def test_to_dict(self):
        job = create_job("s1", "yt", "ig")
        data = job.to_dict()
        assert "job_id" in data
        assert "session_id" in data
        assert "stage" in data
        assert "progress" in data
        assert "_task" not in data  # internal field excluded

    def test_list_jobs_all(self):
        create_job("s1", "yt1", "ig1")
        create_job("s2", "yt2", "ig2")
        jobs = list_jobs()
        assert len(jobs) == 2

    def test_list_jobs_filtered_by_session(self):
        create_job("s1", "yt1", "ig1")
        create_job("s2", "yt2", "ig2")
        create_job("s1", "yt3", "ig3")
        jobs = list_jobs(session_id="s1")
        assert len(jobs) == 2
        assert all(j["session_id"] == "s1" for j in jobs)

    def test_list_jobs_empty_session(self):
        create_job("s1", "yt", "ig")
        jobs = list_jobs(session_id="nonexistent")
        assert len(jobs) == 0
