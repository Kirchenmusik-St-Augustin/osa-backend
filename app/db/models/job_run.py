import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    FetchedValue,
    Index,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base
from app.db.uuid_pk import uuid_pk

# Native Postgres ENUMs, plain string literals (no bound Python enum class
# -- see booking_type_enum in app.db.models.booking_log for the identical
# precedent, this sidesteps SQLAlchemy's values_callable pitfall
# structurally since that code path only triggers for a bound enum class).
job_id_enum = Enum(
    "purge_stale_booking_requests",
    "notify_upcoming_booking_status",
    "purge_expired_password_reset_tokens",
    "purge_old_request_logs",
    "backup_koofr",
    "downsync",
    name="job_id",
)
job_run_status_enum = Enum("success", "failure", name="job_run_status")


class JobRun(Base):
    """One completed run of a scheduled cron job (app.worker.cron_config's
    six job ids -- on-demand mail tasks in app.worker.tasks are out of
    scope, they have no schedule to report a "last run" against).

    `job_id` is NOT a foreign key despite the name -- it mirrors
    CronSchedule.job_id's existing string vocabulary (there is no `jobs`
    table), kept as a native ENUM instead of free text so an unrecognized
    value fails loudly at the database level rather than silently
    (see position_type/booking_type for the established precedent for
    this project's fixed-value-list columns).

    No stage/environment column: each deployment stage has its own
    physically separate Postgres database, so this table is naturally
    stage-local already. Deliberately excluded from pg_dump's row data
    (see backup_service.run_backup()) and explicitly preserved across a
    restore (see backup_service.run_restore()) so a production->dev/test
    downsync never mixes another stage's run history into this one.

    `duration_seconds` is a generated column rather than a Python-computed
    value -- this project's own rule against storing derivable values.
    `created_at`/`updated_at` follow the standard project-wide audit-trail
    pair even though a run row is never updated after insert (`created_at`
    ends up near-identical to `finished_at` for that reason) -- no
    exception carved out, consistent with every other non-junction table.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(
            "finished_at >= started_at", name="job_runs_finished_after_started_check"
        ),
        Index("job_runs_job_id_started_at_index", "job_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[str] = mapped_column(job_id_enum)
    status: Mapped[str] = mapped_column(job_run_status_enum)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Decimal] = mapped_column(
        Numeric,
        Computed("EXTRACT(EPOCH FROM (finished_at - started_at))", persisted=True),
    )
    output: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_onupdate=FetchedValue()
    )
