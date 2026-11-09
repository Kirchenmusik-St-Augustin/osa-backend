"""Pins the public API contract.

Every route, parameter and response schema the frontend relies on is part of
the OpenAPI document. The document is compared with a committed snapshot, so
an API change is never an accident: whoever changes the API regenerates the
snapshot on purpose, and the diff of the snapshot shows the change to the
reviewer.

After an intended API change, regenerate the snapshot with:

    python -m tests.test_openapi_snapshot
"""

import difflib
import json
import sys
from pathlib import Path

from main import app

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "openapi.json"
REGENERATE_COMMAND = "python -m tests.test_openapi_snapshot"

# The whole document is hundreds of kilobytes: a failing comparison shows the
# first changes only, the full diff is one `git diff` away after regenerating.
_MAX_DIFF_LINES = 60


def render_openapi() -> str:
    """The OpenAPI document in the canonical form stored in the snapshot."""
    return (
        json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def describe_drift(snapshot: str, current: str) -> str | None:
    """Explain how the current document differs from the snapshot, or None."""
    if current == snapshot:
        return None
    diff = list(
        difflib.unified_diff(
            snapshot.splitlines(),
            current.splitlines(),
            fromfile="snapshot",
            tofile="current",
            lineterm="",
            n=2,
        )
    )
    shown = "\n".join(diff[:_MAX_DIFF_LINES])
    omitted = len(diff) - _MAX_DIFF_LINES
    more = f"\n... and {omitted} more diff lines" if omitted > 0 else ""
    return (
        "The OpenAPI document no longer matches the committed snapshot "
        f"{SNAPSHOT_PATH.name}. If the API change is intended, regenerate the "
        f"snapshot with `{REGENERATE_COMMAND}` and commit it with the change; "
        f"otherwise undo the change.\n\n{shown}{more}"
    )


def test_openapi_document_matches_the_committed_snapshot() -> None:
    drift = describe_drift(SNAPSHOT_PATH.read_text(encoding="utf-8"), render_openapi())

    assert drift is None, drift


def test_no_drift_is_reported_for_identical_documents() -> None:
    assert describe_drift('{\n  "a": 1\n}\n', '{\n  "a": 1\n}\n') is None


def test_drift_report_names_the_change_and_the_regeneration_command() -> None:
    drift = describe_drift('{\n  "a": 1\n}\n', '{\n  "a": 2\n}\n')

    assert drift is not None
    assert REGENERATE_COMMAND in drift
    assert '-  "a": 1' in drift
    assert '+  "a": 2' in drift


def test_drift_report_cuts_a_long_diff_short() -> None:
    snapshot = "".join(f'"line {number}"\n' for number in range(500))
    current = "".join(f'"changed {number}"\n' for number in range(500))

    drift = describe_drift(snapshot, current)

    assert drift is not None
    assert "more diff lines" in drift
    assert len(drift.splitlines()) < 100


if __name__ == "__main__":
    SNAPSHOT_PATH.parent.mkdir(exist_ok=True)
    SNAPSHOT_PATH.write_text(render_openapi(), encoding="utf-8")
    sys.stdout.write(f"Wrote {SNAPSHOT_PATH}\n")
