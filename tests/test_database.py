from sqlalchemy import text

from app.db.database import get_db


def test_get_db_session_enforces_foreign_keys():
    for session in get_db():
        result = session.execute(text("PRAGMA foreign_keys"))
        assert result.scalar() == 1
        break


def test_get_db_session_can_query_legacy_schema():
    for session in get_db():
        result = session.execute(text("SELECT count(*) FROM performances"))
        assert result.scalar() == 0
        break
