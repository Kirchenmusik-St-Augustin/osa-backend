"""create set_updated_at trigger function

Revision ID: e56ce1ea52e1
Revises: 11ce36d7ccee
Create Date: 2026-09-08 15:15:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e56ce1ea52e1"
down_revision: str | Sequence[str] | None = "11ce36d7ccee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Shared BEFORE UPDATE trigger function for every created_at/updated_at
    # audit-column table (see the next two migrations): unconditionally
    # stamps NEW.updated_at with the current transaction's timestamp on
    # every UPDATE, regardless of whether the UPDATE statement itself
    # already carried some other value for updated_at -- the whole point
    # of an audit trigger is that application code can no longer spoof
    # this column. now() (not clock_timestamp()) is deliberate: it matches
    # created_at's own server_default=func.now() (next migration), which
    # is also transaction-start time, not per-statement wall-clock time --
    # both columns stay on the same time base within one transaction.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP FUNCTION set_updated_at();")
