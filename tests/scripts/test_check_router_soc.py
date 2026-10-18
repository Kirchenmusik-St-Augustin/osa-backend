"""Regression tests for scripts/check_router_soc.py."""

from unittest.mock import patch

import pytest

import scripts.check_router_soc as check_router_soc


def test_find_violations_empty_when_clean() -> None:
    assert check_router_soc.find_violations() == {}


def test_pattern_matches_persistence_model_imports() -> None:
    pattern = check_router_soc.MODEL_IMPORT_PATTERN
    assert pattern.search("from app.db.models.user import User")
    assert pattern.search("import app.db.models.user")
    assert pattern.search("    from app.db.models.artist import Artist")


def test_pattern_does_not_match_other_imports() -> None:
    pattern = check_router_soc.MODEL_IMPORT_PATTERN
    assert not pattern.search("from app.db.database import get_db")
    assert not pattern.search("from app.api.auth_guards import AuthUser")
    assert not pattern.search("from app.services import artist_service")
    assert not pattern.search("from app.db.models_extra import Thing")
    assert not pattern.search("db.commit()")


def test_find_violations_detects_a_model_import(tmp_path) -> None:
    router_dir = tmp_path / "router_includes"
    router_dir.mkdir()
    (router_dir / "bad.py").write_text(
        "from app.db.models.user import User\n\n\ndef f(user: User) -> None: ...\n"
    )

    with patch.object(check_router_soc, "ROUTER_DIR", router_dir):
        violations = check_router_soc.find_violations()

    assert violations == {
        router_dir / "bad.py": [(1, "from app.db.models.user import User")]
    }


def _violations_of(tmp_path, source: str) -> dict:
    router_dir = tmp_path / "router_includes"
    router_dir.mkdir()
    (router_dir / "router.py").write_text(source)
    with patch.object(check_router_soc, "ROUTER_DIR", router_dir):
        return check_router_soc.find_violations()


def test_find_violations_detects_bad_file(tmp_path) -> None:
    router_dir = tmp_path / "router_includes"
    router_dir.mkdir()
    (router_dir / "bad.py").write_text("def f():\n    return db.query(Foo).all()\n")
    (router_dir / "good.py").write_text("def f():\n    return service.get_foo(db)\n")

    with patch.object(check_router_soc, "ROUTER_DIR", router_dir):
        violations = check_router_soc.find_violations()

    assert list(violations.keys()) == [router_dir / "bad.py"]
    assert violations[router_dir / "bad.py"] == [(2, "return db.query(Foo).all()")]


@pytest.mark.parametrize("method", sorted(check_router_soc.SESSION_METHODS))
def test_every_session_method_is_detected_on_the_conventional_name(
    tmp_path, method: str
) -> None:
    violations = _violations_of(tmp_path, f"def f(db):\n    db.{method}(x)\n")

    assert [lineno for _, hits in violations.items() for lineno, _ in hits] == [2]


def test_a_session_under_another_name_is_detected_through_its_annotation(
    tmp_path,
) -> None:
    source = (
        "from typing import Annotated\n"
        "from sqlalchemy.orm import Session\n\n\n"
        "def f(session: Annotated[Session, Depends(get_db)]):\n"
        "    session.commit()\n"
        "    return session.scalars(select(X))\n"
    )

    violations = _violations_of(tmp_path, source)

    assert [lineno for _, hits in violations.items() for lineno, _ in hits] == [6, 7]


def test_methods_of_other_objects_are_not_flagged(tmp_path) -> None:
    source = (
        "def f(items, foo_db, session):\n"
        "    items.add(1)\n"
        "    foo_db.commit()\n"
        "    session.add(2)\n"
    )

    assert _violations_of(tmp_path, source) == {}


def test_main_exits_zero_when_clean(capsys) -> None:
    with (
        patch.object(check_router_soc, "find_violations", return_value={}),
        pytest.raises(SystemExit) as exc_info,
    ):
        check_router_soc.main()
    assert exc_info.value.code == 0
    assert "OK" in capsys.readouterr().out


def test_main_exits_one_with_violations(capsys) -> None:
    fake_path = check_router_soc.ROUTER_DIR / "bad.py"
    violations = {fake_path: [(5, "db.query(Foo)")]}
    with (
        patch.object(check_router_soc, "find_violations", return_value=violations),
        pytest.raises(SystemExit) as exc_info,
    ):
        check_router_soc.main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert "5: db.query(Foo)" in out
