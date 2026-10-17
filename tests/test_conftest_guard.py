"""The guard at the top of conftest.py runs at import time, so it is exercised
in a fresh interpreter: the suite drops and rebuilds the 'public' schema of the
database it is pointed at, which must never be a remote or a non-test one."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent


def _import_conftest(database_url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", "import tests.conftest"],
        cwd=_PROJECT_ROOT,
        env={**os.environ, "TEST_DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://test:test@10.255.255.1:5432/test",
        "postgresql://test:test@db.example.com:5432/osa_test",
        "postgresql:///test",
        "postgresql://test:test@localhost.example.com:5432/test",
    ],
)
def test_a_database_on_another_host_is_refused(database_url: str):
    result = _import_conftest(database_url)

    assert result.returncode != 0
    assert "Refusing to run tests against host" in result.stderr


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://osa:secret@127.0.0.1:5432/osa",
        "postgresql://osa:secret@localhost:5432/osa?sslmode=disable",
    ],
)
def test_a_local_database_without_a_test_name_is_refused(database_url: str):
    result = _import_conftest(database_url)

    assert result.returncode != 0
    assert "Refusing to run tests against non-test database" in result.stderr


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://test:test@localhost:5432/test",
        "postgresql://test:test@127.0.0.1:5432/osa_test?sslmode=disable",
        "postgresql://test:test@[::1]:5432/test",
    ],
)
def test_a_local_test_database_is_accepted(database_url: str):
    result = _import_conftest(database_url)

    assert result.returncode == 0, result.stderr
