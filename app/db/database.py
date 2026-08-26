from collections.abc import Generator
from typing import cast

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# Settings._validate_tier1 already exits the process if database_url is
# unset, so by the time get_settings() returns, it is guaranteed non-None.
SQLALCHEMY_DATABASE_URL = cast("str", get_settings().database_url)

# Synchronous SQLAlchemy (Session, no AsyncSession/asyncpg/greenlet).
# Schritt 1 originally chose the async engine; switched back here (User
# decision, 2026-07-28) because osa-backend is a low-concurrency internal
# scheduling tool (never more than ~10 concurrent users observed in
# practice) -- async's real benefit
# (serving many concurrent in-flight I/O waits without consuming a thread
# each) buys nothing at this scale, while it already cost one concrete bug
# class (coverage.py silently losing the trace across greenlet_spawn,
# see the now-removed `concurrency = ["greenlet"]` in pyproject.toml).
#
# pool_pre_ping: pings a pooled connection before handing it out,
# transparently reconnecting if the server dropped it (e.g. after a
# pg_restore or a network blip) instead of surfacing a stale-connection
# error on the next request.
engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True)

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
