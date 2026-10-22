"""enforce artist, auth log, user agent and location colour rules in the database

Revision ID: a7b8c9d0e1f2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-20 14:00:00.000000

The application already requires a surname and a given name for an artist,
four-digit years and no death before birth, writes an event and a time for
every auth log row, stores user agents clipped to 512 characters and accepts
six hex digits as the colour of a location; the database now enforces each of
these as well. Production was checked beforehand: no artist without a name or
with an invalid year, no auth log row without event or time, no user agent
longer than 512 characters (the longest has 320) and all locations carry six
hex digits.
"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ARTIST_YEARS_RULE = (
    "(birthyear IS NULL OR birthyear BETWEEN 1000 AND 9999) "
    "AND (deathyear IS NULL OR deathyear BETWEEN 1000 AND 9999) "
    "AND (birthyear IS NULL OR deathyear IS NULL OR deathyear >= birthyear)"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("artists", "surname", nullable=False)
    op.alter_column("artists", "givenname", nullable=False)
    op.create_check_constraint("artists_years_check", "artists", ARTIST_YEARS_RULE)
    op.alter_column("auth_logs", "event", nullable=False)
    op.alter_column("auth_logs", "fired_at", nullable=False)
    op.create_check_constraint(
        "client_user_agents_string_length_check",
        "client_user_agents",
        "char_length(string) <= 512",
    )
    op.create_check_constraint(
        "locations_color_check", "locations", "color ~ '^[0-9a-fA-F]{6}$'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("locations_color_check", "locations", type_="check")
    op.drop_constraint(
        "client_user_agents_string_length_check", "client_user_agents", type_="check"
    )
    op.alter_column("auth_logs", "fired_at", nullable=True)
    op.alter_column("auth_logs", "event", nullable=True)
    op.drop_constraint("artists_years_check", "artists", type_="check")
    op.alter_column("artists", "givenname", nullable=True)
    op.alter_column("artists", "surname", nullable=True)
