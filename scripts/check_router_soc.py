#!/usr/bin/env python3
"""Guards against business logic (direct DB access) and persistence models
creeping back into FastAPI routers.

Routers must call service functions only - every call of a session method
(query, add, commit, execute, get, scalars, ...) on a Session parameter,
whatever it is called, belongs in app/services/*.py, and a router never
imports from app.db.models. The authenticated-user type comes
from app.api.auth_guards (AuthUser), and mapping an ORM object to a response
schema is a service function.

Usage:
    python scripts/check_router_soc.py
"""

import ast
import re
import sys
from pathlib import Path

ROUTER_DIR = Path(__file__).resolve().parent.parent / "app" / "api" / "router_includes"

MODEL_IMPORT_PATTERN = re.compile(r"^\s*(from|import)\s+app\.db\.models\b")

# Methods of a SQLAlchemy Session that read or write: a router must not call
# any of them, whatever it names the session parameter.
SESSION_METHODS = frozenset(
    {
        "query",
        "add",
        "add_all",
        "commit",
        "rollback",
        "flush",
        "execute",
        "scalar",
        "scalars",
        "get",
        "delete",
        "merge",
        "refresh",
    }
)

# The conventional name counts even without an annotation.
_CONVENTIONAL_SESSION_NAME = "db"


def _mentions_session(annotation: ast.expr | None) -> bool:
    return annotation is not None and any(
        isinstance(node, ast.Name) and node.id == "Session"
        for node in ast.walk(annotation)
    )


def _session_parameter_names(tree: ast.Module) -> set[str]:
    names = {
        argument.arg
        for function in ast.walk(tree)
        if isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef)
        for argument in (*function.args.args, *function.args.kwonlyargs)
        if _mentions_session(argument.annotation)
    }
    return names | {_CONVENTIONAL_SESSION_NAME}


def _session_call_linenos(tree: ast.Module) -> set[int]:
    session_names = _session_parameter_names(tree)
    return {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in SESSION_METHODS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in session_names
    }


def find_violations() -> dict[Path, list[tuple[int, str]]]:
    violations: dict[Path, list[tuple[int, str]]] = {}
    for path in sorted(ROUTER_DIR.glob("*.py")):
        source = path.read_text()
        lines = source.splitlines()
        flagged = _session_call_linenos(ast.parse(source)) | {
            lineno
            for lineno, line in enumerate(lines, start=1)
            if MODEL_IMPORT_PATTERN.search(line)
        }
        if flagged:
            violations[path] = [
                (lineno, lines[lineno - 1].strip()) for lineno in sorted(flagged)
            ]
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
