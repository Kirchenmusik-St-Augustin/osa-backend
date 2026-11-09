"""make created_at required on every table that still allowed NULL

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-20 19:00:00.000000

A creation time that can be NULL cannot answer "when was this row created",
and a writer that passes an explicit NULL silently produces more of them.
Rows from before the column had its default get their updated_at (the nearest
known moment) or, without one, the time of this migration. Production was
checked beforehand: one artist and five users have no creation time, the
five users all carry an updated_at. updated_at stays nullable on purpose: the
trigger sets it on the first update, a row that was never updated has none.
"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES: list[str] = [
    "artists",
    "booking_logs",
    "booking_requests",
    "bookings",
    "choirjobs",
    "client_user_agents",
    "fees",
    "instruments",
    "job_runs",
    "locations",
    "ordinariumwork_positions",
    "ordinariumworks",
    "password_reset_tokens",
    "performance_positions",
    "performance_proprium",
    "performance_rehearsals",
    "performances",
    "personal_access_tokens",
    "propriumelements",
    "propriumworks",
    "request_logs",
    "roles",
    "scores",
    "sent_emails",
    "shorturls",
    "user_positions",
    "user_roles",
    "users",
    "voices",
]


def upgrade() -> None:
    """Upgrade schema."""
    for table in _TABLES:
        op.execute(
            f"UPDATE {table} SET created_at = COALESCE(updated_at, now()) "  # noqa: S608
            "WHERE created_at IS NULL"
        )
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(_TABLES):
        op.alter_column(
            table,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
        )
