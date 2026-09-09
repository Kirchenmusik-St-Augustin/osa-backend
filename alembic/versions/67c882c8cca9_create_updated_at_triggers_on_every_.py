"""create updated_at triggers on every audit-column table

Revision ID: 67c882c8cca9
Revises: 0936ab290fc2
Create Date: 2026-09-08 15:15:20.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "67c882c8cca9"
down_revision: str | Sequence[str] | None = "0936ab290fc2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every table with both created_at and updated_at (26 total: 7 via the two
# shared mixins, 19 individually declared) -- password_reset_tokens is
# deliberately excluded (created_at only, no updated_at to maintain).
# Postgres trigger names are scoped per-table (pg_trigger's uniqueness is
# on (tgname, tgrelid), not tgname alone), so every table below can reuse
# the same trigger name without conflict.
_AUDIT_TABLES: list[str] = [
    "choirjobs",
    "instruments",
    "locations",
    "propriumelements",
    "voices",
    "ordinariumworks",
    "propriumworks",
    "artists",
    "bookings",
    "booking_logs",
    "booking_requests",
    "fees",
    "ordinariumwork_positions",
    "performances",
    "performance_positions",
    "performance_proprium",
    "performance_rehearsals",
    "personal_access_tokens",
    "request_logs",
    "roles",
    "scores",
    "sent_emails",
    "shorturls",
    "users",
    "user_positions",
    "user_roles",
]

_TRIGGER_NAME = "set_updated_at"


def upgrade() -> None:
    """Upgrade schema."""
    for table in _AUDIT_TABLES:
        op.execute(
            f"CREATE TRIGGER {_TRIGGER_NAME} "
            f"BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table in reversed(_AUDIT_TABLES):
        op.execute(f"DROP TRIGGER {_TRIGGER_NAME} ON {table};")
