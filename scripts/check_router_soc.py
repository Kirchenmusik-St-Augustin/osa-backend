#!/usr/bin/env python3
"""Guards against business logic (direct DB access) and persistence models
creeping back into FastAPI routers.

Routers must call service functions only - actual db.query()/db.add()/
db.commit()/db.execute()/db.delete() calls belong in app/services/*.py, and a
router never imports from app.db.models. The authenticated-user type comes
from app.api.auth_guards (AuthUser), and mapping an ORM object to a response
schema is a service function.

Usage:
    python scripts/check_router_soc.py
"""

import re
import sys
from pathlib import Path

ROUTER_DIR = Path(__file__).resolve().parent.parent / "app" / "api" / "router_includes"

VIOLATION_PATTERN = re.compile(
    r"\bdb\.(query|add|commit|execute|delete)\(|^\s*(from|import)\s+app\.db\.models\b"
)


def find_violations() -> dict[Path, list[tuple[int, str]]]:
    violations: dict[Path, list[tuple[int, str]]] = {}
    for path in sorted(ROUTER_DIR.glob("*.py")):
        hits = [
            (lineno, line.strip())
            for lineno, line in enumerate(path.read_text().splitlines(), start=1)
            if VIOLATION_PATTERN.search(line)
        ]
        if hits:
            violations[path] = hits
    return violations


def main() -> None:
    violations = find_violations()
    if not violations:
        print(
            "check_router_soc: OK - routers call services only "
            "(no direct DB access, no model imports)."
        )
        sys.exit(0)

    print(
        "check_router_soc: FAILED - routers must call service functions only and "
        "never import persistence models.\n"
    )
    for path, hits in violations.items():
        print(f"{path.relative_to(ROUTER_DIR.parent.parent.parent)}:")
        for lineno, line in hits:
            print(f"  {lineno}: {line}")
    sys.exit(1)


if __name__ == "__main__":
    main()
