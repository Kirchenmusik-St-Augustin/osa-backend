import logging
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.job_run import JobRun
from app.services import job_run_service
from app.services.job_run_service import get_latest_run_per_job, record_job_run


class TestRecordJobRun:
    def test_round_trips_status_output_and_timestamps(self, db_session: Session):
        started_at = datetime(2026, 9, 1, 5, 0, tzinfo=UTC)

        record_job_run(
            "purge_stale_booking_requests",
            started_at,
            status="success",
            output="deleted 3 rows",
        )

        run = db_session.execute(select(JobRun)).scalar_one()
        assert run.job_id == "purge_stale_booking_requests"
        assert run.status == "success"
        assert run.output == "deleted 3 rows"
        assert run.started_at == started_at
        assert run.finished_at >= started_at
        assert run.duration_seconds >= 0

    def test_output_none_round_trips_as_null(self, db_session: Session):
        record_job_run(
            "purge_old_request_logs",
            datetime.now(UTC),
            status="success",
            output=None,
        )

        run = db_session.execute(select(JobRun)).scalar_one()
        assert run.output is None

    def test_a_db_failure_is_swallowed_and_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        def failing_session_local() -> None:
            msg = "connection refused"
            raise RuntimeError(msg)

        monkeypatch.setattr(job_run_service, "SessionLocal", failing_session_local)

        with caplog.at_level(logging.ERROR):
            record_job_run(
                "backup_koofr", datetime.now(UTC), status="failure", output="boom"
            )

        assert "failed to record job run" in caplog.text.lower()


class TestGetLatestRunPerJob:
    def test_returns_only_the_newest_row_per_job(self, db_session: Session):
        older = datetime(2026, 9, 1, 6, 0, tzinfo=UTC)
        newer = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)
        db_session.add_all(
            [
                JobRun(
                    job_id="backup_koofr",
                    status="failure",
                    started_at=older,
                    finished_at=older + timedelta(seconds=1),
                    output="first attempt failed",
                ),
                JobRun(
                    job_id="backup_koofr",
                    status="success",
                    started_at=newer,
                    finished_at=newer + timedelta(seconds=1),
                ),
                JobRun(
                    job_id="downsync",
                    status="success",
                    started_at=older,
                    finished_at=older + timedelta(seconds=1),
                ),
            ]
        )
        db_session.commit()

        latest = get_latest_run_per_job(db_session)

        assert latest.keys() == {"backup_koofr", "downsync"}
        assert latest["backup_koofr"].status == "success"
        assert latest["backup_koofr"].started_at == newer

    def test_returns_empty_dict_when_no_runs_exist(self, db_session: Session):
        assert get_latest_run_per_job(db_session) == {}

    def test_query_count_does_not_scale_with_job_or_run_count(
        self, db_session: Session, count_queries
    ):
        with count_queries() as one_job:
            get_latest_run_per_job(db_session)

        started_at = datetime(2026, 9, 1, tzinfo=UTC)
        for job_id in (
            "purge_stale_booking_requests",
            "notify_upcoming_booking_status",
            "purge_expired_password_reset_tokens",
            "purge_old_request_logs",
            "backup_koofr",
            "downsync",
        ):
            for offset in range(3):
                run_start = started_at + timedelta(hours=offset)
                db_session.add(
                    JobRun(
                        job_id=job_id,
                        status="success",
                        started_at=run_start,
                        finished_at=run_start,
                    )
                )
        db_session.commit()

        with count_queries() as six_jobs:
            get_latest_run_per_job(db_session)

        assert six_jobs.count == one_job.count
