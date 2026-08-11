from collections.abc import Generator
from typing import cast

from sqlalchemy import create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from app.core.config import get_settings

# Settings._validate_tier1 already exits the process if database_url is
# unset, so by the time get_settings() returns, it is guaranteed non-None.
SQLALCHEMY_DATABASE_URL = cast("str", get_settings().database_url)

# Synchronous SQLAlchemy (Session, no AsyncSession/aiosqlite/greenlet) --
# 1:1 vb-api's stack. Schritt 1 originally chose the async engine; switched
# back here (User decision, 2026-07-28) because both osa-backend and vb-api
# are low-concurrency internal scheduling tools (never more than ~10
# concurrent users observed on either in practice) -- async's real benefit
# (serving many concurrent in-flight I/O waits without consuming a thread
# each) buys nothing at this scale, while it already cost one concrete bug
# class (coverage.py silently losing the trace across greenlet_spawn,
# see the now-removed `concurrency = ["greenlet"]` in pyproject.toml).
#
# check_same_thread=False: FastAPI runs sync `def` path operations in a
# worker threadpool, so a pooled connection can be checked out by a
# different thread than the one that opened it -- never concurrently
# though, SQLAlchemy's pool guarantees exclusive checkout per connection,
# which is exactly what makes lifting sqlite3's same-thread restriction
# safe here.
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(  # pyright: ignore[reportUnusedFunction] -- registered as an event callback, not called directly
    dbapi_connection: DBAPIConnection, _connection_record: ConnectionPoolEntry
) -> None:
    # SQLite disables FK enforcement by default, per connection -- without
    # this, the legacy schema's FKs (bookings -> performances, etc.) are
    # silently unenforced. Fires once per new DBAPI connection.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# Named SessionLocal (not e.g. SyncSessionLocal) so the existing ruff
# banned-api rule in pyproject.toml
# ([tool.ruff.lint.flake8-tidy-imports.banned-api],
# "app.db.database.SessionLocal") already covers it.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
