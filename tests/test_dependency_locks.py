"""The dependency locks stay hash-pinned and every install command checks them."""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[1]
_LOCK_FILES = ("requirements.lock", "requirements-dev.lock")
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")


def _pin_blocks(lock_text: str) -> list[str]:
    """Split a lock file into one text block per pinned requirement."""
    blocks: list[str] = []
    for line in lock_text.splitlines():
        if re.match(r"[A-Za-z0-9]", line):
            blocks.append(line)
        elif blocks:
            blocks[-1] += "\n" + line
    return blocks


def _lines_containing(path: Path, command: str) -> list[str]:
    return [line for line in path.read_text().splitlines() if command in line]


@pytest.mark.parametrize("lock_file", _LOCK_FILES)
def test_every_pin_in_the_lock_carries_release_file_hashes(lock_file: str):
    blocks = _pin_blocks((_ROOT / lock_file).read_text())

    assert blocks
    unhashed = [block.splitlines()[0] for block in blocks if not _HASH.search(block)]
    assert unhashed == []


def test_dockerfile_installs_both_locks_with_hash_checking():
    installs = _lines_containing(_ROOT / "Dockerfile", "RUN pip install")

    assert len(installs) == 2
    assert all("--require-hashes" in line for line in installs)


def test_pipeline_installs_the_dev_lock_with_hash_checking():
    installs = _lines_containing(
        _ROOT / ".github" / "workflows" / "ci-cd.yml", "uv pip install"
    )

    assert len(installs) == 2
    assert all("--require-hashes" in line for line in installs)
