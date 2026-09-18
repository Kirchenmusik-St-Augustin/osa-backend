"""add unique constraint on client_user_agents.string

Revision ID: 7354bd6bc11e
Revises: 81b6a7304006
Create Date: 2026-09-17 22:01:10.306130

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7354bd6bc11e"
down_revision: str | Sequence[str] | None = "81b6a7304006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # request_log_service._get_or_create_client_user_agent()'s get-or-create
    # runs on every HTTP request without one -- the constraint is what
    # makes its IntegrityError-based race handling correct rather than
    # merely optimistic. Verified against both dev and production data
    # beforehand: zero duplicate `string` values in either database, so
    # this applies cleanly.
    op.create_unique_constraint(
        "client_user_agents_string_key", "client_user_agents", ["string"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "client_user_agents_string_key", "client_user_agents", type_="unique"
    )
