"""add job_runs table

Revision ID: 81b6a7304006
Revises: b38dcbca4172
Create Date: 2026-09-14 15:00:00.000000

"""

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "81b6a7304006"
down_revision: str | Sequence[str] | None = "b38dcbca4172"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRIGGER_NAME = "set_updated_at"

# create_type=False: CREATE TYPE/DROP TYPE are issued explicitly below
# instead of relying on op.create_table()'s/op.drop_table()'s
# auto-management -- verified empirically that the two are asymmetric for a
# brand-new table: op.create_table() auto-creates a bare inline sa.Enum's
# type correctly, but op.drop_table() only ever receives a table NAME, not
# its former columns, so it cannot know to cascade a DROP TYPE. Left
# unhandled, a downgrade orphans both enum types, and the next upgrade then
# fails with "type already exists". Same reasoning as
# fa9e6613c5c1_convert_booking_type_to_enum.py's booking_type_enum,
# applied here to two brand-new types instead of one pre-existing column.
_job_id_enum = postgresql.ENUM(
    "purge_stale_booking_requests",
    "notify_upcoming_booking_status",
    "purge_expired_password_reset_tokens",
    "purge_old_request_logs",
    "backup_koofr",
    "downsync",
    name="job_id",
    create_type=False,
)
_job_run_status_enum = postgresql.ENUM(
    "success", "failure", name="job_run_status", create_type=False
)


def upgrade() -> None:
    """Upgrade schema."""
    _job_id_enum.create(op.get_bind(), checkfirst=False)
    _job_run_status_enum.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Uuid(), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("job_id", _job_id_enum, nullable=False),
        sa.Column("status", _job_run_status_enum, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "duration_seconds",
            sa.Numeric(),
            sa.Computed(
                "EXTRACT(EPOCH FROM (finished_at - started_at))", persisted=True
            ),
            nullable=False,
        ),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "finished_at >= started_at", name="job_runs_finished_after_started_check"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "job_runs_job_id_started_at_index", "job_runs", ["job_id", "started_at"]
    )
    op.execute(
        f"CREATE TRIGGER {_TRIGGER_NAME} "
        "BEFORE UPDATE ON job_runs "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DROP TRIGGER {_TRIGGER_NAME} ON job_runs;")
    op.drop_index("job_runs_job_id_started_at_index", table_name="job_runs")
    op.drop_table("job_runs")
    _job_id_enum.drop(op.get_bind(), checkfirst=False)
    _job_run_status_enum.drop(op.get_bind(), checkfirst=False)
