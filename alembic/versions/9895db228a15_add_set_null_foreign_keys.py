"""add set null foreign keys

Revision ID: 9895db228a15
Revises: 1319fb6d1fac
Create Date: 2026-09-10 10:56:55.041954

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9895db228a15"
down_revision: str | Sequence[str] | None = "1319fb6d1fac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# booking_logs.performance_id/user_id are NOT NULL today; ON DELETE SET
# NULL requires them nullable first, matching the documented intent that
# these historical log rows survive the Performance or User they describe.
_NULLABLE_PREP: list[tuple[str, str]] = [
    ("booking_logs", "performance_id"),
    ("booking_logs", "user_id"),
]

# Pre-existing rows referencing a since-deleted Performance/User predate
# this constraint (accumulated back when the columns had no FK at all --
# deleting a Performance never touched booking_logs). Backfilling them to
# NULL here is not data loss: it converts an already-dangling integer into
# the exact NULL-reference shape the new SET NULL behavior produces for any
# future deletion, so a fresh ADD CONSTRAINT can validate every remaining
# row. Written as a subquery so it is correct regardless of which specific
# rows are orphaned on a given database.
_ORPHAN_CLEANUP: list[tuple[str, str, str]] = [
    ("booking_logs", "performance_id", "performances"),
    ("booking_logs", "user_id", "users"),
]

# Each row below is: constraint name, source table, source column,
# referent table.
_SET_NULL_FKS: list[tuple[str, str, str, str]] = [
    (
        "booking_logs_performance_id_fkey",
        "booking_logs",
        "performance_id",
        "performances",
    ),
    ("booking_logs_user_id_fkey", "booking_logs", "user_id", "users"),
    (
        "request_logs_client_user_agent_id_fkey",
        "request_logs",
        "client_user_agent_id",
        "client_user_agents",
    ),
    ("request_logs_user_id_fkey", "request_logs", "user_id", "users"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _NULLABLE_PREP:
        op.alter_column(table, column, existing_type=sa.Integer(), nullable=True)
    for table, column, referent in _ORPHAN_CLEANUP:
        # table/column/referent come from the fixed literal list above, not
        # from any external input -- not an injection risk.
        op.execute(
            f"UPDATE {table} SET {column} = NULL "  # noqa: S608
            f"WHERE {column} IS NOT NULL "
            f"AND {column} NOT IN (SELECT id FROM {referent})"
        )
    for name, table, column, referent in _SET_NULL_FKS:
        op.create_foreign_key(
            name, table, referent, [column], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    """Downgrade schema.

    Dropping the SET NULL constraints themselves is always safe. Restoring
    NOT NULL on booking_logs.performance_id/user_id is NOT unconditionally
    safe: if any parent Performance or User was actually deleted while this
    migration was live, the corresponding booking_logs rows now genuinely
    hold NULL, and Postgres will raise NotNullViolation here. That failure
    is intentional, not a bug in this migration -- it surfaces real
    orphaned history that a blind downgrade must not silently paper over
    (e.g. by deleting those rows or backfilling a fake id). Operators
    hitting this must decide case by case (delete the affected log rows,
    or abandon the downgrade) before this migration can complete.
    """
    for name, table, _column, _referent in reversed(_SET_NULL_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
    for table, column in reversed(_NULLABLE_PREP):
        op.alter_column(table, column, existing_type=sa.Integer(), nullable=False)
