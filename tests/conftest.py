"""Shared pytest fixtures.

The test suite runs against a dedicated PostgreSQL database
(TEST_DATABASE_URL, falling back to DATABASE_URL) -- not a throwaway
per-session file (see git history for that earlier fixture setup). Schema
comes from the real Alembic migrations (command.upgrade(..., "head")), not
Base.metadata.create_all() -- running the actual migration here is what
would catch model/migration drift, not just a fixture rebuilt from the
models themselves. Env vars are set at module level, BEFORE `main`/
`app.db.database` are imported, because app/db/database.py builds its
module-level singleton engine from get_settings().database_url at import
time (E402 is already allowed project-wide for exactly this reason, see
pyproject.toml).

Per-test isolation is the vb-fastapi-vue sister project's transaction+
SAVEPOINT pattern (db_session below), not the earlier "plain get_db()
generator, data persists across tests" model this suite used against its
throwaway-per-session file. That original model relied on tests
picking mutually-unique fixture data (uuid-suffixed emails, monotonic
`itertools.count()` ids in a few files) to avoid collisions -- against
real Postgres, with the full suite's actual connection/session traffic
(the scheduler's advisory lock among it), that discipline alone turned out
to not be quite enough: a full-suite run occasionally produced a handful
of failures that never reproduced in isolation or on a second full run,
consistent with a rare timing-dependent cross-test interaction rather than
a deterministic bug in any one test. Wrapping every test in its own
transaction, rolled back afterward regardless of how the test or the code
under test committed, removes the shared mutable state that a timing
window could ever act on -- the same reasoning vb-api already applied.
"""

import os

os.environ["APP_ENVIRONMENT"] = "test"
os.environ["CORS_ORIGINS"] = "http://localhost:21001"
os.environ["SECRET_KEY"] = "test-secret-key-" + "x" * 32

# Guards against ever pointing this at a real dev/prod database: the
# session fixture below drops and rebuilds the entire 'public' schema.
_ALLOWED_TEST_DBS = {"osa_test", "test"}
_TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get(
    "DATABASE_URL"
)
if not _TEST_DATABASE_URL:
    msg = (
        "TEST_DATABASE_URL (or DATABASE_URL) is not set. Point it at a "
        "dedicated PostgreSQL test database, e.g. "
        "postgresql://osa:<pw>@127.0.0.1:5432/osa_test."
    )
    raise RuntimeError(msg)

_dbname = _TEST_DATABASE_URL.rsplit("/", 1)[-1].split("?")[0]
if _dbname not in _ALLOWED_TEST_DBS:
    msg = (
        f"Refusing to run tests against non-test database {_dbname!r}. "
        f"Allowed test database names: {sorted(_ALLOWED_TEST_DBS)}. The "
        "test session drops and rebuilds the 'public' schema -- pointing "
        "this at a real dev/prod database would destroy it."
    )
    raise RuntimeError(msg)

os.environ["DATABASE_URL"] = _TEST_DATABASE_URL  # consulted by alembic/env.py too

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, selectinload, sessionmaker

from alembic import command
from app.api.middleware import request_logging
from app.core import mailer
from app.core.config import get_settings
from app.core.security import get_password_hash
from app.db.database import engine, get_db
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_role import UserRole
from app.services import booking_jobs, housekeeping_jobs
from main import app

if engine.dialect.name != "postgresql":
    msg = f"Test suite requires PostgreSQL, got dialect {engine.dialect.name!r}."
    raise RuntimeError(msg)

_ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(Config(str(_ALEMBIC_INI)), "head")


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Plain module-level holder, not a ContextVar: TestClient runs the ASGI app
# in a separate worker thread via an anyio blocking portal, and ContextVar
# values set in the test thread don't reliably propagate there (1:1 vb-api's
# own conftest.py). The suite runs fully serially (no pytest-xdist), so a
# single module global is safe.
_active_session: Session | None = None


@pytest.fixture(autouse=True)
def _db_transaction():
    """Wraps every test in one outer transaction on its own connection,
    always rolled back in the finally-block below -- regardless of how many
    times the test body or the code under test called db.commit(). Every
    Session handed out during the test (both this fixture's own db_session
    and, via override_get_db() below, every request client makes) is bound
    to that same connection with join_transaction_mode="create_savepoint",
    so an application-level commit() only releases/reopens a SAVEPOINT
    nested inside the still-open outer transaction instead of ending it."""
    global _active_session  # see the module-level docstring above

    connection = engine.connect()
    trans = connection.begin()
    session = TestingSessionLocal(
        bind=connection, join_transaction_mode="create_savepoint"
    )
    _active_session = session
    try:
        yield session
    finally:
        _active_session = None
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def db_session(_db_transaction: Session) -> Session:
    return _db_transaction


def override_get_db() -> Iterator[Session]:
    assert _active_session is not None, "no active per-test session/transaction"
    yield _active_session  # not closed here -- _db_transaction above owns it


app.dependency_overrides[get_db] = override_get_db


class _NonClosingSession:
    """Proxies a Session but no-ops close() -- lets code that opens its own
    `db = SessionLocal(); try: ...; finally: db.close()` (see
    pyproject.toml's TID251 exemptions: booking_jobs.py,
    housekeeping_jobs.py, mailer.py, request_logging.py -- none of them
    have a request context to inject Depends(get_db) through) safely
    operate on the CURRENT test's own per-test session instead of a
    genuinely independent connection, without that close() call
    prematurely closing a session the test still needs afterward."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def close(self) -> None:
        pass  # _db_transaction owns the real close/rollback, see above

    def __getattr__(self, name: str) -> object:
        return getattr(self._session, name)


def _job_session_factory() -> _NonClosingSession:
    """Permanent stand-in for SessionLocal in every TID251-exempted module
    (assigned once below, not per-test) -- looks up _active_session fresh
    on every call, since request_logging.py's middleware in particular
    opens a new one per request, potentially many times across one test.

    Without this, each of those modules' real SessionLocal() would open a
    genuinely independent connection: at best invisible to the current
    test's still-uncommitted fixture data (silently wrong assertions, e.g.
    a scheduled job finding nothing to act on), at worst a real deadlock
    against it (an INSERT there blocking on a row this test's own
    still-open transaction already holds a lock on, which only that
    transaction's own end-of-test rollback would ever release -- observed
    in practice while building this fixture, see the migration plan's M5
    section). Just as importantly, without this every request made through
    `client` durably commits its own request_logging row via a real,
    independent connection -- never rolled back by _db_transaction below,
    so those rows would silently accumulate for the rest of the pytest
    session across every test that ever calls a real endpoint.
    """
    assert _active_session is not None, "no active per-test session/transaction"
    return _NonClosingSession(_active_session)


booking_jobs.SessionLocal = _job_session_factory
housekeeping_jobs.SessionLocal = _job_session_factory
mailer.SessionLocal = _job_session_factory
request_logging.SessionLocal = _job_session_factory


@pytest.fixture
def client():
    with TestClient(app, base_url="http://testserver") as c:
        # The lifespan startup above already ran start_scheduler(), which
        # reads get_settings() to decide whether to register backup_koofr --
        # caching a Settings snapshot from BEFORE the test body's own
        # monkeypatch.setenv() calls run. Clear it again so the test body
        # always observes its own env changes, not whatever was true at
        # app-startup time.
        get_settings.cache_clear()
        yield c


@pytest.fixture
def make_user(db_session: Session) -> Callable[..., User]:
    """Factory fixture: creates a persisted User (unique email per call
    unless overridden), optionally attached to Role rows (created
    on-the-fly, reused by name if already present in this test's session).
    Defaults to `verified=True` -- most tests need a normal, working user
    (get_verified_user() gates almost every endpoint); pass
    `verified=False` for the few tests exercising unverified-user
    behavior."""

    def _make_user(
        *,
        email: str | None = None,
        password: str = "correct-horse-battery-staple",
        roles: list[str] | None = None,
        administrator: bool = False,
        auth_locked: bool = False,
        verified: bool = True,
    ) -> User:
        user = User(
            surname="Muster",
            givenname=f"Test-{uuid.uuid4().hex[:8]}",
            email=email or f"test-{uuid.uuid4().hex}@example.test",
            auth_password=get_password_hash(password),
            auth_locked=auth_locked,
            administrator=administrator,
            email_verified_at=datetime.now(UTC) if verified else None,
        )
        db_session.add(user)
        db_session.flush()

        for role_name in roles or []:
            result = db_session.execute(select(Role).where(Role.name == role_name))
            role = result.scalar_one_or_none()
            if role is None:
                role = Role(name=role_name, label=role_name, order=0)
                db_session.add(role)
                db_session.flush()
            db_session.add(UserRole(user_id=user.id, role_id=role.id))

        db_session.commit()

        # Plain refresh() doesn't eager-load relationships -- re-fetch with
        # roles pre-loaded so calculate_permissions() never lazy-loads
        # outside the request's session (a lazy-load outside an open
        # session would raise DetachedInstanceError otherwise).
        result = db_session.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user.id)
        )
        return result.scalar_one()

    return _make_user


class QueryCounter:
    """Counts SQL statements executed on the test engine while active."""

    def __init__(self) -> None:
        self.count = 0


_SAVEPOINT_PREFIXES = ("SAVEPOINT", "RELEASE SAVEPOINT", "ROLLBACK TO SAVEPOINT")


@pytest.fixture
def count_queries() -> Callable[[], Iterator["QueryCounter"]]:
    """Yield a factory for a context manager that counts executed SQL
    statements, e.g. `with count_queries() as counter: ...; assert
    counter.count <= N` -- used to assert N+1 query patterns don't
    regress (1:1 vb-api pattern, CLAUDE.md testing_constraints)."""

    @contextmanager
    def _count_queries() -> Iterator[QueryCounter]:
        counter = QueryCounter()

        def _on_execute(
            _conn: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: bool,
        ) -> None:
            # _db_transaction's join_transaction_mode="create_savepoint"
            # (see above) transparently opens/releases a SAVEPOINT around
            # every db.commit() a test or the code under test makes -- SQL
            # the test-isolation machinery issues, not the application, so
            # it must not count toward an N+1 guard's query budget.
            if statement.lstrip().upper().startswith(_SAVEPOINT_PREFIXES):
                return
            counter.count += 1

        event.listen(engine, "before_cursor_execute", _on_execute)
        try:
            yield counter
        finally:
            event.remove(engine, "before_cursor_execute", _on_execute)

    return _count_queries
