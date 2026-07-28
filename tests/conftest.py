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

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
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
