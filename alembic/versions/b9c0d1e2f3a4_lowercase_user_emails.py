"""store user e-mail addresses in lower case and enforce it

Revision ID: b9c0d1e2f3a4
Revises: f1a2b3c4d5e6
Create Date: 2026-10-16 10:30:00.000000

Registration already lowercases addresses, administrator-created accounts did
not, while login compared the typed address case-sensitively. Production was
checked beforehand: no two addresses differ only by case, so the unique
constraint cannot collide. Existing access tokens of the affected users (the
token subject is the address) stop working once and are replaced by the next
refresh.
"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b9c0d1e2f3a4"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("UPDATE users SET email = lower(email) WHERE email <> lower(email)")
    op.create_check_constraint(
        "users_email_lowercase_check", "users", "email IS NULL OR email = lower(email)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("users_email_lowercase_check", "users", type_="check")
