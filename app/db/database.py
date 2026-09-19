from collections.abc import Generator
from typing import cast

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# Settings._validate_tier1 already exits the process if database_url is
# unset, so by the time get_settings() returns, it is guaranteed non-None.
SQLALCHEMY_DATABASE_URL = cast("str", get_settings().database_url)

# Synchronous SQLAlchemy (Session, no AsyncSession/asyncpg/greenlet):
# osa-backend is a low-concurrency internal scheduling tool (never more
# than ~10 concurrent users observed in practice), so async's real benefit
# (serving many concurrent in-flight I/O waits without consuming a thread
# each) buys nothing at this scale, while it comes with a concrete bug
# class (coverage.py silently losing the trace across greenlet_spawn).
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


def get_db() -> Generator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
