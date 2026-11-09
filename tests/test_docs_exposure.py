"""The interactive documentation and the OpenAPI document list every route and
schema, so production must not serve them. The app is built at import time, so
the real behaviour is checked in a fresh interpreter per environment."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from main import _docs_urls

_PROJECT_ROOT = Path(__file__).parent.parent
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

_PROBE = """
import json
import sys
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)
print(json.dumps({path: client.get(path).status_code for path in sys.argv[1:]}))
"""


def _statuses_in_environment(environment: str) -> dict[str, int]:
    result = subprocess.run(  # noqa: S603 -- fixed argument list, no shell
        [sys.executable, "-c", _PROBE, *_DOCS_PATHS],
        cwd=_PROJECT_ROOT,
        env={**os.environ, "APP_ENVIRONMENT": environment},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_production_has_no_documentation_urls():
    assert _docs_urls("production") == (None, None, None)


@pytest.mark.parametrize("environment", ["development", "test", "qa"])
def test_other_environments_keep_the_documentation_urls(environment: str):
    assert _docs_urls(environment) == ("/docs", "/redoc", "/openapi.json")


def test_production_answers_not_found_for_the_documentation():
    assert _statuses_in_environment("production") == dict.fromkeys(_DOCS_PATHS, 404)


@pytest.mark.parametrize("environment", ["development", "qa"])
def test_non_production_serves_the_documentation(environment: str):
    assert _statuses_in_environment(environment) == dict.fromkeys(_DOCS_PATHS, 200)
