"""add missing foreign key indexes

Revision ID: a1b2c3d4e5f6
Revises: d1e2f3a4b5c6
Create Date: 2026-10-17 09:00:00.000000

"""

from typing import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column) of every foreign key that had no index on its referencing
# column. Without one, deleting or updating a parent row scans the whole
# child table and joins from the parent side are unindexed. Index names
# follow the "<table>_<column>_index" convention of the existing indexes.
_FK_INDEXES: list[tuple[str, str]] = [
    ("booking_logs", "user_id"),
    ("booking_requests", "user_id"),
    ("oauth2_bindings", "local_id"),
    ("ordinariumworks", "artist_id"),
    ("performance_proprium", "propriumelement_id"),
    ("performance_proprium", "propriumwork_id"),
    ("performances", "artist_id"),
    ("performances", "location_id"),
    ("performances", "ordinariumwork_id"),
    ("propriumworks", "artist_id"),
    ("request_logs", "client_user_agent_id"),
    ("request_logs", "user_id"),
    ("user_roles", "role_id"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, column in _FK_INDEXES:
        op.create_index(f"{table}_{column}_index", table, [column])


def downgrade() -> None:
    """Downgrade schema."""
    for table, column in reversed(_FK_INDEXES):
        op.drop_index(f"{table}_{column}_index", table_name=table)
