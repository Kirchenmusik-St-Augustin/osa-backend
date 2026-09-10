"""add score count check constraints

Revision ID: 1f1716b2a4f1
Revises: 372cab77ea9b
Create Date: 2026-09-10 21:04:45.963909

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f1716b2a4f1"
down_revision: str | Sequence[str] | None = "372cab77ea9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every one of these 42 columns is a physical count (holdings quantities,
# instrumentation headcounts) already validated `Field(ge=0, ...)` at the
# Pydantic layer (app/schemas/score.py) but never enforced in the
# database -- same gap 521f1ba5e919 closed for the money columns.
_COUNT_CHECKS: list[str] = [
    "geboren",
    "gestorben",
    "jahr",
    "part1anz",
    "part2anz",
    "klausz1anz",
    "klausz2anz",
    "chorpart1anz",
    "chorpart2anz",
    "stsopranz",
    "staltanz",
    "sttenanz",
    "stbassanz",
    "orgelanz",
    "violine1",
    "violine2",
    "viola",
    "cello",
    "contrabass",
    "floete1",
    "floete2",
    "floete3",
    "oboe1",
    "oboe2",
    "klarinette1",
    "klarinette2",
    "fagott1",
    "fagott2",
    "kontrafagott",
    "trombalt",
    "trombten",
    "trombbass",
    "corno1",
    "corno2",
    "trompete1",
    "trompete2",
    "trompete3",
    "pauke",
    "soinstr1anz",
    "soinstr2anz",
    "soinstr3anz",
    "soinstr4anz",
]


def upgrade() -> None:
    """Upgrade schema."""
    for column in _COUNT_CHECKS:
        op.create_check_constraint(f"scores_{column}_check", "scores", f"{column} >= 0")


def downgrade() -> None:
    """Downgrade schema."""
    for column in reversed(_COUNT_CHECKS):
        op.drop_constraint(f"scores_{column}_check", "scores", type_="check")
