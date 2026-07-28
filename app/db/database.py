from collections.abc import AsyncGenerator
from typing import cast

from sqlalchemy import event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import ConnectionPoolEntry, NullPool

from app.core.config import get_settings

# Settings._validate_tier1 already exits the process if database_url is
# unset, so by the time get_settings() returns, it is guaranteed non-None.
SQLALCHEMY_DATABASE_URL = cast("str", get_settings().database_url)

# SQLite has no real connection pool, and aiosqlite runs each connection's
# blocking sqlite3 calls on its own dedicated background thread -- NullPool
# (fresh connection per checkout, closed on return) avoids sharing one
# aiosqlite connection across concurrent async tasks.
engine = create_async_engine(SQLALCHEMY_DATABASE_URL, poolclass=NullPool)


@event.listens_for(engine.sync_engine, "connect")
def _enable_sqlite_foreign_keys(  # pyright: ignore[reportUnusedFunction] -- registered as an event callback, not called directly
    dbapi_connection: DBAPIConnection, _connection_record: ConnectionPoolEntry
) -> None:
    # SQLite disables FK enforcement by default, per connection -- without
    # this, the legacy schema's FKs (bookings -> performances, etc.) are
    # silently unenforced. Fires once per new DBAPI connection, i.e. once
    # per checkout under NullPool.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Named SessionLocal (not e.g. AsyncSessionLocal) so the existing ruff
# banned-api rule in pyproject.toml
# ([tool.ruff.lint.flake8-tidy-imports.banned-api],
# "app.db.database.SessionLocal") already covers it.
SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
