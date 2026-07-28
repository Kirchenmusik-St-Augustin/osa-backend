"""Shared pytest fixtures.

Builds an isolated, throwaway SQLite file per test session from the
committed schema-only fixture (tests/fixtures/legacy_schema.sql) -- NOT the
619 MB database/database.sqlite at the repo root, which is far too large
for git/CI (see scripts/dump_test_schema.py to regenerate). Env vars are
set at module level, BEFORE `main`/`app.db.database` are imported, because
app/db/database.py builds its module-level singleton engine from
get_settings().database_url at import time (E402 is already allowed
project-wide for exactly this reason, see pyproject.toml).
"""

import os
import sqlite3
import tempfile
from pathlib import Path

_FIXTURE_SCHEMA = Path(__file__).parent / "fixtures" / "legacy_schema.sql"
_tmp_dir = tempfile.mkdtemp(prefix="osa-backend-test-db-")
_TEST_DB_PATH = Path(_tmp_dir) / "test.sqlite"

with sqlite3.connect(_TEST_DB_PATH) as _conn:
    _conn.executescript(_FIXTURE_SCHEMA.read_text())

os.environ["APP_ENVIRONMENT"] = "test"
os.environ["CORS_ORIGINS"] = "http://localhost:21001"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret-key-" + "x" * 32

import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.security import get_password_hash
from app.db.database import get_db
from app.db.models.role import Role
from app.db.models.user import User
from app.db.models.user_role import UserRole
from main import app


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async for session in get_db():
        yield session
        break


@pytest.fixture
async def make_user(
    db_session: AsyncSession,
) -> Callable[..., Coroutine[None, None, User]]:
    """Factory fixture: creates a persisted User (unique email per call
    unless overridden), optionally attached to Role rows (created
    on-the-fly, reused by name if already present in this test's session)."""

    async def _make_user(
        *,
        email: str | None = None,
        password: str = "correct-horse-battery-staple",
        roles: list[str] | None = None,
        administrator: bool = False,
        auth_locked: bool = False,
    ) -> User:
        user = User(
            surname="Muster",
            givenname=f"Test-{uuid.uuid4().hex[:8]}",
            email=email or f"test-{uuid.uuid4().hex}@example.test",
            auth_password=get_password_hash(password),
            auth_locked=auth_locked,
            administrator=administrator,
        )
        db_session.add(user)
        await db_session.flush()

        for role_name in roles or []:
            result = await db_session.execute(
                select(Role).where(Role.name == role_name)
            )
            role = result.scalar_one_or_none()
            if role is None:
                role = Role(name=role_name, label=role_name, order=0)
                db_session.add(role)
                await db_session.flush()
            db_session.add(UserRole(user_id=user.id, role_id=role.id))

        await db_session.commit()

        # Plain refresh() doesn't eager-load relationships -- re-fetch with
        # roles pre-loaded so calculate_permissions() never lazy-loads
        # outside the request's async context (MissingGreenlet otherwise).
        result = await db_session.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user.id)
        )
        return result.scalar_one()

    return _make_user
