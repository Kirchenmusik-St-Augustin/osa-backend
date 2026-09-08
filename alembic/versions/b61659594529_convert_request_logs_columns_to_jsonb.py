"""convert request_logs columns to jsonb

Revision ID: b61659594529
Revises: ea9883f8b469
Create Date: 2026-09-08 11:54:23.481765

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b61659594529"
down_revision: str | Sequence[str] | None = "ea9883f8b469"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The JSON escape sequence for the Unicode NUL code point (U+0000): a
# backslash followed by the six characters "u0000" -- not a real NUL byte
# itself, which no SQL text value can ever hold.
_NUL_CODEPOINT_ESCAPE = "\\u0000"


def upgrade() -> None:
    """Upgrade schema."""
    # All three columns already hold manually json.dumps()-encoded text.
    # A read-only IS JSON check found 0 syntactically invalid rows, but
    # IS JSON doesn't catch every case a varchar -> jsonb cast can choke
    # on: two rows (automated scanner traffic against the public /go/
    # shorturl redirect, a random binary payload wrapped in a JSON body)
    # contain the NUL codepoint escape defined above, which Postgres
    # accepts as valid JSON syntax but can never represent as text/jsonb.
    # Strips just that escape sequence before the cast -- the rest of
    # each JSON value, and every other row, passes through byte-for-byte
    # unchanged.
    for column in ("client_ips", "request_input", "response_content"):
        op.execute(
            f"UPDATE request_logs SET {column} = replace({column}, "  # noqa: S608
            f"'{_NUL_CODEPOINT_ESCAPE}', '') "
            f"WHERE {column} LIKE '%{_NUL_CODEPOINT_ESCAPE}%'"
        )
    op.alter_column(
        "request_logs",
        "client_ips",
        existing_type=sa.String(),
        type_=postgresql.JSONB(),
        postgresql_using="client_ips::jsonb",
        existing_nullable=True,
    )
    op.alter_column(
        "request_logs",
        "request_input",
        existing_type=sa.String(),
        type_=postgresql.JSONB(),
        postgresql_using="request_input::jsonb",
        existing_nullable=True,
    )
    op.alter_column(
        "request_logs",
        "response_content",
        existing_type=sa.String(),
        type_=postgresql.JSONB(),
        postgresql_using="response_content::jsonb",
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # jsonb -> text is Postgres' canonical JSON text representation, not
    # necessarily byte-identical to the original json.dumps() output
    # (whitespace/key order may differ) -- semantically equivalent JSON,
    # which is all any consumer of these columns ever relied on. The two
    # rows whose NUL codepoint escape was stripped in upgrade() stay
    # stripped -- that data cleanup is a one-way improvement, not
    # something a schema downgrade should undo.
    op.alter_column(
        "request_logs",
        "response_content",
        existing_type=postgresql.JSONB(),
        type_=sa.String(),
        postgresql_using="response_content::text",
        existing_nullable=True,
    )
    op.alter_column(
        "request_logs",
        "request_input",
        existing_type=postgresql.JSONB(),
        type_=sa.String(),
        postgresql_using="request_input::text",
        existing_nullable=True,
    )
    op.alter_column(
        "request_logs",
        "client_ips",
        existing_type=postgresql.JSONB(),
        type_=sa.String(),
        postgresql_using="client_ips::text",
        existing_nullable=True,
    )
