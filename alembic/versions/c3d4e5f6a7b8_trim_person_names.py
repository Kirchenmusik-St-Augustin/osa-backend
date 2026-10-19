"""remove surrounding whitespace from user and artist names

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-10-19 12:00:00.000000

The unique constraint on (surname, givenname) compares the stored text, so
"Anna" and "Anna " counted as two people and the registration check could not
see that a name was taken. Input is stripped from now on; this removes the
padding that is already stored.

A row is only trimmed when no other row already holds the trimmed name, so the
constraint cannot fail. One case is resolved on purpose: when the trimmed name
of an active account is already held by a deleted account (a duplicate that
was registered because of the padding), the deleted account's given name gets
the suffix "_geloescht", which makes the duplicate recognisable in the list of
deleted users, and the active account then loses its padding. Any other
collision leaves the affected rows unchanged.

The cleanup is not reversed on downgrade: the removed padding and the suffix
cannot be reconstructed.
"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DELETED_ACCOUNT_SUFFIX = "_geloescht"


def _trimmed(column: str) -> str:
    return f"regexp_replace({column}, '^\\s+|\\s+$', '', 'g')"


def _is_padded(alias: str) -> str:
    return (
        f"({alias}.surname <> {_trimmed(alias + '.surname')} "
        f"OR {alias}.givenname <> {_trimmed(alias + '.givenname')})"
    )


def _trim_table(table: str) -> str:
    # The table name is one of two constants below, never input.
    return f"""
        UPDATE {table}
        SET surname = {_trimmed(table + ".surname")},
            givenname = {_trimmed(table + ".givenname")}
        WHERE {_is_padded(table)}
          AND NOT EXISTS (
            SELECT 1 FROM {table} AS other
            WHERE other.id <> {table}.id
              AND {_trimmed("other.surname")} = {_trimmed(table + ".surname")}
              AND {_trimmed("other.givenname")} = {_trimmed(table + ".givenname")}
          )
    """  # noqa: S608


MARK_DELETED_DUPLICATES = f"""
    UPDATE users AS deleted_account
    SET givenname = deleted_account.givenname || '{DELETED_ACCOUNT_SUFFIX}'
    WHERE deleted_account.deleted_at IS NOT NULL
      AND EXISTS (
        SELECT 1 FROM users AS padded
        WHERE padded.id <> deleted_account.id
          AND padded.deleted_at IS NULL
          AND {_is_padded("padded")}
          AND {_trimmed("padded.surname")} = deleted_account.surname
          AND {_trimmed("padded.givenname")} = deleted_account.givenname
      )
"""  # noqa: S608


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(MARK_DELETED_DUPLICATES)
    op.execute(_trim_table("users"))
    op.execute(_trim_table("artists"))


def downgrade() -> None:
    """Downgrade schema."""
