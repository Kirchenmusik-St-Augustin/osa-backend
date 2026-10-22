"""name the template key of a sent mail and require what every mail has

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-10-20 20:00:00.000000

The column `headers` never held MIME headers of the mail the application
sends: it holds the key of the template ("password-reset"). It is called
template_key now. Rows from earlier years still carry the raw header text of
the mail in that column; they stay as they are. The mailer writes sender,
subject, body and template key for every mail, so the four columns are
required. Production was checked beforehand: no row without any of them.
"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIRED = ("from", "subject", "body", "template_key")


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("sent_emails", "headers", new_column_name="template_key")
    for column in _REQUIRED:
        op.alter_column("sent_emails", column, nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    for column in reversed(_REQUIRED):
        op.alter_column("sent_emails", column, nullable=True)
    op.alter_column("sent_emails", "template_key", new_column_name="headers")
