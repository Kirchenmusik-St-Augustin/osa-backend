from collections.abc import Generator
from typing import cast

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# Settings._validate_tier1 already exits the process if database_url is
# unset, so by the time get_settings() returns, it is guaranteed non-None.
SQLALCHEMY_DATABASE_URL = cast("str", get_settings().database_url)

# Synchronous SQLAlchemy (Session, no AsyncSession/asyncpg/greenlet):
# osa-backend is a low-concurrency internal scheduling tool (rarely more
# than 50 concurrent users), so async's real benefit
# (serving many concurrent in-flight I/O waits without consuming a thread
# each) buys nothing at this scale, while it comes with a concrete bug
# class (coverage.py silently losing the trace across greenlet_spawn).
# ARCHITECTURE_DECISIONS.md (ADR-2) records this exception and when to
# revisit it.
#
# pool_pre_ping: pings a pooled connection before handing it out,
# transparently reconnecting if the server dropped it (e.g. after a
# pg_restore or a network blip) instead of surfacing a stale-connection
# error on the next request.
#
# The pool and the server-side limits keep one slow or runaway statement
# from holding a connection until every other request waits for it: a
# request thread waits at most 10 seconds for a pooled connection, a
# statement runs at most 30 seconds, waits for a lock at most 10 seconds and
# an open transaction may sit idle for at most a minute. Restore and backup
# run in their own pg_restore/pg_dump/psql subprocesses and are not bound by
# these limits; the migrations use their own connection (alembic/env.py).
_POOL_SIZE = 5
_POOL_MAX_OVERFLOW = 5
_POOL_TIMEOUT_SECONDS = 10
_CONNECTION_OPTIONS = (
    "-c statement_timeout=30000 "
    "-c idle_in_transaction_session_timeout=60000 "
    "-c lock_timeout=10000 "
    "-c application_name=osa-backend"
)
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=_POOL_SIZE,
    max_overflow=_POOL_MAX_OVERFLOW,
    pool_timeout=_POOL_TIMEOUT_SECONDS,
    connect_args={"options": _CONNECTION_OPTIONS},
)

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
