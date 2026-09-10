"""add cascade foreign keys

Revision ID: 81159257db39
Revises: 9895db228a15
Create Date: 2026-09-10 10:56:56.153302

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "81159257db39"
down_revision: str | Sequence[str] | None = "9895db228a15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ordinariumwork_positions rows referencing a since-deleted Ordinariumwork
# predate ordinariumwork_service.delete_ordinariumwork()'s own cleanup of
# this exact table -- they have no meaning without their parent. Removing
# them here is exactly what ON DELETE CASCADE would already have done had
# that Ordinariumwork's deletion gone through the current code path, so a
# fresh ADD CONSTRAINT can validate every remaining row.
_ORDINARIUMWORK_POSITIONS_ORPHAN_CLEANUP = (
    "DELETE FROM ordinariumwork_positions "
    "WHERE ordinariumwork_id NOT IN (SELECT id FROM ordinariumworks)"
)

# Every one of these columns already has the service deleting the parent
# manually clean up this exact child table first (e.g.
# ordinariumwork_service.delete_ordinariumwork(), performance_service.
# delete_performance()) -- CASCADE moves that cleanup to the database,
# making the now-redundant manual delete() calls in those services safe to
# remove. Each row below is: constraint name, source table, source column,
# referent table.
_CASCADE_FKS: list[tuple[str, str, str, str]] = [
    ("oauth2_bindings_local_id_fkey", "oauth2_bindings", "local_id", "users"),
    (
        "ordinariumwork_positions_ordinariumwork_id_fkey",
        "ordinariumwork_positions",
        "ordinariumwork_id",
        "ordinariumworks",
    ),
    (
        "performance_positions_performance_id_fkey",
        "performance_positions",
        "performance_id",
        "performances",
    ),
    (
        "performance_proprium_performance_id_fkey",
        "performance_proprium",
        "performance_id",
        "performances",
    ),
    (
        "performance_rehearsals_performance_id_fkey",
        "performance_rehearsals",
        "performance_id",
        "performances",
    ),
    ("booking_requests_user_id_fkey", "booking_requests", "user_id", "users"),
    ("user_positions_user_id_fkey", "user_positions", "user_id", "users"),
]


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(_ORDINARIUMWORK_POSITIONS_ORPHAN_CLEANUP)
    for name, table, column, referent in _CASCADE_FKS:
        op.create_foreign_key(
            name, table, referent, [column], ["id"], ondelete="CASCADE"
        )


def downgrade() -> None:
    """Downgrade schema.

    Pure constraint removal, always reversible at the schema level. Rows
    already removed by a CASCADE that fired while this migration was live
    (or by the one-time orphan cleanup above) stay removed -- that data
    loss is the correct, expected consequence of a delete that already
    happened, not something downgrade can or should undo.
    """
    for name, table, _column, _referent in reversed(_CASCADE_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
