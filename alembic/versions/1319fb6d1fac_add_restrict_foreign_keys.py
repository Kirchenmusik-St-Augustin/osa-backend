"""add restrict foreign keys

Revision ID: 1319fb6d1fac
Revises: 67c882c8cca9
Create Date: 2026-09-10 10:56:53.971507

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1319fb6d1fac"
down_revision: str | Sequence[str] | None = "67c882c8cca9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every one of these columns already has a service-layer dependency check
# that blocks deleting the referenced row while a child row exists (e.g.
# performance_service._has_bookings_or_requests(), artist_service.
# _artist_has_dependencies()) -- RESTRICT enforces that same invariant at
# the database level as a defense-in-depth backstop, it never fires under
# normal application use.
# Each row below is: constraint name, source table, source column,
# referent table.
_RESTRICT_FKS: list[tuple[str, str, str, str]] = [
    ("bookings_performance_id_fkey", "bookings", "performance_id", "performances"),
    ("bookings_user_id_fkey", "bookings", "user_id", "users"),
    (
        "booking_requests_performance_id_fkey",
        "booking_requests",
        "performance_id",
        "performances",
    ),
    (
        "performance_proprium_propriumelement_id_fkey",
        "performance_proprium",
        "propriumelement_id",
        "propriumelements",
    ),
    (
        "performance_proprium_propriumwork_id_fkey",
        "performance_proprium",
        "propriumwork_id",
        "propriumworks",
    ),
    ("performances_location_id_fkey", "performances", "location_id", "locations"),
    (
        "performances_ordinariumwork_id_fkey",
        "performances",
        "ordinariumwork_id",
        "ordinariumworks",
    ),
    ("performances_artist_id_fkey", "performances", "artist_id", "artists"),
    ("ordinariumworks_artist_id_fkey", "ordinariumworks", "artist_id", "artists"),
    ("propriumworks_artist_id_fkey", "propriumworks", "artist_id", "artists"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for name, table, column, referent in _RESTRICT_FKS:
        op.create_foreign_key(
            name, table, referent, [column], ["id"], ondelete="RESTRICT"
        )


def downgrade() -> None:
    """Downgrade schema."""
    for name, table, _column, _referent in reversed(_RESTRICT_FKS):
        op.drop_constraint(name, table, type_="foreignkey")
