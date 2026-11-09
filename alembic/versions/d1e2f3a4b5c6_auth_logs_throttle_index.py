"""index auth_logs for the login throttle lookups

Revision ID: d1e2f3a4b5c6
Revises: b9c0d1e2f3a4
Create Date: 2026-10-16 11:00:00.000000

"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """check_login_throttle() filters auth_logs by lower(email), event and
    the time window on every login attempt; without an index each attempt
    scans the whole, ever-growing table."""
    op.create_index(
        "auth_logs_email_event_fired_at_index",
        "auth_logs",
        [sa.text("lower(email)"), "event", "fired_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("auth_logs_email_event_fired_at_index", table_name="auth_logs")
