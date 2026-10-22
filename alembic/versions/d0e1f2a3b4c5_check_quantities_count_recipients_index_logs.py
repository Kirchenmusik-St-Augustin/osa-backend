"""check position quantities, count mail recipients in the database, index log times

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-20 17:00:00.000000

The forms accept a head count of 1 to 99 for a position; the database now
refuses anything else, because a zero or negative count would silently remove
or invert a position when the regular and the standby places are computed.

The mail kill switch used to load every mail of its window and split the
comma separated address lists in Python. The database counts the recipients
itself now (a stored generated column with the same result as the former
Python count), and an index on created_at serves the window filter and the
month listing of the sent mails. The request log, the fastest growing table,
gets the same index for the nightly retention job and the monthly listing.
Production was checked beforehand: all quantities are between 1 and 96.
"""

from typing import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Whitespace around an address list or a comma is not part of an address, and
# an empty element ("a,,b", "a, ,b") is not an address.
RECIPIENT_COUNT_EXPRESSION = " + ".join(
    "cardinality(array_remove(regexp_split_to_array("
    f"regexp_replace(coalesce(\"{column}\", ''), '^\\s+|\\s+$', '', 'g'), "
    "'\\s*,\\s*'), ''))"
    for column in ("to", "cc", "bcc")
)


def upgrade() -> None:
    """Upgrade schema."""
    for table in ("ordinariumwork_positions", "performance_positions"):
        op.create_check_constraint(
            f"{table}_quantity_check", table, "quantity BETWEEN 1 AND 99"
        )
    op.add_column(
        "sent_emails",
        sa.Column(
            "recipient_count",
            sa.Integer(),
            sa.Computed(RECIPIENT_COUNT_EXPRESSION, persisted=True),
            nullable=False,
        ),
    )
    op.create_index("sent_emails_created_at_index", "sent_emails", ["created_at"])
    op.create_index("request_logs_created_at_index", "request_logs", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("request_logs_created_at_index", table_name="request_logs")
    op.drop_index("sent_emails_created_at_index", table_name="sent_emails")
    op.drop_column("sent_emails", "recipient_count")
    for table in ("performance_positions", "ordinariumwork_positions"):
        op.drop_constraint(f"{table}_quantity_check", table, type_="check")
