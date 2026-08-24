import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.db.database import get_db


def test_get_db_session_enforces_foreign_keys():
    """Postgres enforces FK constraints natively and unconditionally.
    user_roles is the one table with a real ForeignKey (see
    app/db/models/user_role.py); a role_id that doesn't exist must be
    rejected, not silently inserted."""
    insert_orphan = text(
        "INSERT INTO user_roles (user_id, role_id) VALUES (:user_id, :role_id)"
    )
    for session in get_db():
        with pytest.raises(IntegrityError, match="foreign key constraint"):
            session.execute(insert_orphan, {"user_id": -1, "role_id": -1})
        session.rollback()
        break


def test_get_db_session_can_query_legacy_schema():
    """A plain smoke test that the legacy schema is queryable at all --
    not a row-count assertion: `performances` used to always be empty
    (pre-Schritt-5), but Schritt 5's own tests now populate it in this
    same shared, non-rolled-back test DB (see conftest.py)."""
    for session in get_db():
        result = session.execute(text("SELECT count(*) FROM performances"))
        assert result.scalar() >= 0
        break
