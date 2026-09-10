"""add ondelete to user_roles foreign keys

Revision ID: 486c6e00cbd4
Revises: 81159257db39
Create Date: 2026-09-10 10:56:57.256774

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "486c6e00cbd4"
down_revision: str | Sequence[str] | None = "81159257db39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Postgres cannot ALTER an existing FOREIGN KEY's ON DELETE action in place
# -- both of user_roles' two FKs (created without an explicit ondelete in
# 6e1829d5f417_schema_baseline.py, i.e. Postgres' own default NO ACTION)
# must be dropped and recreated. Names below match Postgres' own default
# "<table>_<column>_fkey" auto-naming, confirmed against pg_constraint
# before writing this migration.
_USER_ROLES_USER_FK = (
    "user_roles_user_id_fkey",
    "user_roles",
    "user_id",
    "users",
    "CASCADE",
)
_USER_ROLES_ROLE_FK = (
    "user_roles_role_id_fkey",
    "user_roles",
    "role_id",
    "roles",
    "RESTRICT",
)


def upgrade() -> None:
    """Upgrade schema.

    user_id -> CASCADE: a role grant is meaningless without its user, and
    no existing check blocks deleting a user for having roles.
    role_id -> RESTRICT: coreelement_service._role_has_dependent_users()
    already blocks deleting a Role that is still assigned to a user --
    CASCADE here would silently strip that user's role grant instead,
    which is security-relevant and must fail loudly instead.
    """
    for name, table, column, referent, ondelete in (
        _USER_ROLES_USER_FK,
        _USER_ROLES_ROLE_FK,
    ):
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name, table, referent, [column], ["id"], ondelete=ondelete
        )


def downgrade() -> None:
    """Downgrade schema.

    Restores both FKs to their original, ondelete-less (Postgres default
    NO ACTION) shape -- matches the exact DDL 6e1829d5f417_schema_baseline
    originally created, so a downgrade round-trip leaves user_roles
    byte-for-byte identical to before this slice.
    """
    for name, table, column, referent, _ondelete in (
        _USER_ROLES_ROLE_FK,
        _USER_ROLES_USER_FK,
    ):
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, referent, [column], ["id"])
