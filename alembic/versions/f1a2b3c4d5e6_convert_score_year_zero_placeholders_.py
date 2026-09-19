"""convert score year-field zero placeholders to NULL

Revision ID: f1a2b3c4d5e6
Revises: bb0c6ceb6e39
Create Date: 2026-09-19 09:30:00.000000

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "bb0c6ceb6e39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Data-only migration: `scores.geboren`/`gestorben`/`jahr` were never a
    real year 0, only the form's former "nothing entered" placeholder. Both
    columns are already nullable, so no schema change is needed -- only the
    existing rows need to switch representation to line up with the API
    layer, which now stores an absent year as NULL instead of 0."""
    op.execute("UPDATE scores SET geboren = NULL WHERE geboren = 0")
    op.execute("UPDATE scores SET gestorben = NULL WHERE gestorben = 0")
    op.execute("UPDATE scores SET jahr = NULL WHERE jahr = 0")


def downgrade() -> None:
    """Restores the 0-placeholder convention. Any row left NULL by manual
    entry after the upgrade (rather than by this migration) is
    indistinguishable from one this migration touched, so this is a
    best-effort revert, not a byte-exact one."""
    op.execute("UPDATE scores SET geboren = 0 WHERE geboren IS NULL")
    op.execute("UPDATE scores SET gestorben = 0 WHERE gestorben IS NULL")
    op.execute("UPDATE scores SET jahr = 0 WHERE jahr IS NULL")
