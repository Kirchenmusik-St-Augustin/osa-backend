"""require a real duration of work and a real year of a score

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-10-19 16:00:00.000000

A work of zero minutes is meaningless in the planning view, and the ordinarium
and the proprium form disagreed on the lowest duration; both now take 1 to 999
and the database enforces it. Likewise year 0 does not exist: "no year" is
NULL, which an earlier data migration already converted, but the checks still
allowed 0 and a form could bring the placeholder back. The three year checks
now require a value above 0. Production was checked beforehand: no duration
outside 1 to 999 and no year 0.
"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

YEAR_COLUMNS = ("geboren", "gestorben", "jahr")
WORK_TABLES = ("ordinariumworks", "propriumworks")
DURATION_RULE = "duration IS NULL OR duration BETWEEN 1 AND 999"


def upgrade() -> None:
    """Upgrade schema."""
    for table in WORK_TABLES:
        op.create_check_constraint(f"{table}_duration_check", table, DURATION_RULE)
    for column in YEAR_COLUMNS:
        # A leftover placeholder would make the stricter check fail.
        op.execute(f"UPDATE scores SET {column} = NULL WHERE {column} = 0")  # noqa: S608
        op.drop_constraint(f"scores_{column}_check", "scores", type_="check")
        op.create_check_constraint(f"scores_{column}_check", "scores", f"{column} > 0")


def downgrade() -> None:
    """Downgrade schema."""
    for column in YEAR_COLUMNS:
        op.drop_constraint(f"scores_{column}_check", "scores", type_="check")
        op.create_check_constraint(f"scores_{column}_check", "scores", f"{column} >= 0")
    for table in WORK_TABLES:
        op.drop_constraint(f"{table}_duration_check", table, type_="check")
