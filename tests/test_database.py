from sqlalchemy import text

from app.db.database import get_db


async def test_get_db_session_enforces_foreign_keys():
    async for session in get_db():
        result = await session.execute(text("PRAGMA foreign_keys"))
        assert result.scalar() == 1
        break


async def test_get_db_session_can_query_legacy_schema():
    async for session in get_db():
        result = await session.execute(text("SELECT count(*) FROM performances"))
        assert result.scalar() == 0
        break
