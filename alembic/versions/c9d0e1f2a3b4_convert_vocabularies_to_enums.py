"""convert fixed vocabularies of text columns to native enums

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-20 16:00:00.000000

The columns below only ever hold a fixed set of words. As free text they
accept any typo; as native enums the database refuses it. The value sets are
the ones the application writes plus the ones that production rows from
earlier years carry (the auth events Attempting, Validated, OtherDeviceLogout
and CurrentDeviceLogout, and the mail transports log, failover and mailgun are
no longer written but stay valid so the history converts). Production was
checked beforehand: every stored value is part of its set.
"""

from typing import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False: CREATE TYPE and DROP TYPE are issued explicitly below,
# the columns are altered in place.
_TYPES: dict[str, postgresql.ENUM] = {
    name: postgresql.ENUM(*values, name=name, create_type=False)
    for name, values in {
        "oauth2_provider": ("google",),
        "http_method": (
            "GET",
            "HEAD",
            "POST",
            "PUT",
            "DELETE",
            "CONNECT",
            "OPTIONS",
            "TRACE",
            "PATCH",
        ),
        "sent_email_mailer": ("smtp", "log", "failover", "mailgun"),
        "auth_event": (
            "Login",
            "Failed",
            "Lockout",
            "Logout",
            "Verified",
            "PasswordReset",
            "Attempting",
            "Validated",
            "OtherDeviceLogout",
            "CurrentDeviceLogout",
        ),
    }.items()
}

# (table, column, enum type, column accepts NULL)
_COLUMNS: list[tuple[str, str, str, bool]] = [
    ("oauth2_bindings", "provider", "oauth2_provider", False),
    ("users", "auth_lastlogin_provider", "oauth2_provider", True),
    ("request_logs", "request_method", "http_method", False),
    ("sent_emails", "mailer", "sent_email_mailer", True),
    ("auth_logs", "event", "auth_event", False),
]


def upgrade() -> None:
    """Upgrade schema."""
    for enum in _TYPES.values():
        enum.create(op.get_bind(), checkfirst=False)
    for table, column, type_name, nullable in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.String(),
            type_=_TYPES[type_name],
            postgresql_using=f"{column}::{type_name}",
            existing_nullable=nullable,
        )


def downgrade() -> None:
    """Downgrade schema."""
    for table, column, type_name, nullable in reversed(_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=_TYPES[type_name],
            type_=sa.String(),
            postgresql_using=f"{column}::varchar",
            existing_nullable=nullable,
        )
    for enum in reversed(list(_TYPES.values())):
        enum.drop(op.get_bind(), checkfirst=False)
