"""Regression tests for scripts/check_coverage_gate.py."""

import json
from typing import TYPE_CHECKING

import pytest

import scripts.check_coverage_gate as gate

if TYPE_CHECKING:
    from pathlib import Path

MINIMUMS_TOML = """
[tool.coverage_gate]
statements = 98.0
branches = 94.0
functions = 98.0
"""


def _function(num_statements: int, covered_lines: int) -> dict[str, object]:
    return {
        "summary": {"num_statements": num_statements, "covered_lines": covered_lines}
    }


def _report(
    *,
    statements: tuple[int, int] = (100, 100),
    branches: tuple[int, int] = (10, 10),
    functions: dict[str, dict[str, object]] | None = None,
    branch_coverage: bool = True,
) -> dict[str, object]:
    return {
        "meta": {"branch_coverage": branch_coverage, "version": "7"},
        "totals": {
            "num_statements": statements[0],
            "covered_lines": statements[1],
            "num_branches": branches[0],
            "covered_branches": branches[1],
        },
        "files": {
            "app/a.py": {
                "functions": functions
                if functions is not None
                else {"": _function(5, 5), "run": _function(3, 3)}
            }
        },
    }


def _write_inputs(
    tmp_path: Path, report: dict[str, object], toml: str = MINIMUMS_TOML
) -> tuple[Path, Path]:
    report_path = tmp_path / "coverage.json"
    pyproject_path = tmp_path / "pyproject.toml"
    report_path.write_text(json.dumps(report))
    pyproject_path.write_text(toml)
    return report_path, pyproject_path


def _measure(report: dict[str, object]) -> gate.Measured:
    return gate.measure(gate._CoverageReport.model_validate(report))


def test_measure_computes_each_metric_separately() -> None:
    measured = _measure(
        _report(
            statements=(200, 190),
            branches=(40, 30),
            functions={"a": _function(2, 2), "b": _function(2, 0)},
        )
    )

    assert measured == gate.Measured(statements=95.0, branches=75.0, functions=50.0)


def test_measure_counts_a_partially_executed_function_as_covered() -> None:
    measured = _measure(_report(functions={"a": _function(4, 1)}))

    assert measured.functions == 100.0


def test_measure_ignores_module_level_and_statement_less_functions() -> None:
    measured = _measure(
        _report(
            functions={
                "": _function(10, 0),
                "stub": _function(0, 0),
                "real": _function(3, 3),
            }
        )
    )

    assert measured.functions == 100.0


def test_measure_reports_full_coverage_when_nothing_is_countable() -> None:
    measured = _measure(
        _report(statements=(0, 0), branches=(0, 0), functions={"": _function(0, 0)})
    )

    assert measured == gate.Measured(statements=100.0, branches=100.0, functions=100.0)


def test_shortfalls_empty_when_every_metric_meets_its_minimum() -> None:
    minimums = gate.GateMinimums(statements=98.0, branches=94.0, functions=98.0)
    measured = gate.Measured(statements=98.0, branches=94.0, functions=100.0)

    assert gate.find_shortfalls(measured, minimums) == []


def test_shortfalls_name_only_the_failing_metrics() -> None:
    minimums = gate.GateMinimums(statements=98.0, branches=94.0, functions=98.0)
    measured = gate.Measured(statements=99.0, branches=93.99, functions=97.5)

    assert gate.find_shortfalls(measured, minimums) == [
        "branches: 93.99% is below the minimum of 94.00%",
        "functions: 97.50% is below the minimum of 98.00%",
    ]


def test_load_report_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(gate.GateError, match="run pytest first"):
        gate.load_report(tmp_path / "coverage.json")


def test_load_report_rejects_a_foreign_json_document(tmp_path: Path) -> None:
    path = tmp_path / "coverage.json"
    path.write_text('{"unrelated": true}')

    with pytest.raises(gate.GateError, match=r"not a coverage\.py JSON report"):
        gate.load_report(path)


def test_load_report_rejects_a_report_without_branch_data(tmp_path: Path) -> None:
    report_path, _ = _write_inputs(tmp_path, _report(branch_coverage=False))

    with pytest.raises(gate.GateError, match="branch = true"):
        gate.load_report(report_path)


def test_load_minimums_reads_the_gate_table(tmp_path: Path) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(MINIMUMS_TOML + "\n[tool.other]\nkey = 1\n")

    assert gate.load_minimums(path) == gate.GateMinimums(
        statements=98.0, branches=94.0, functions=98.0
    )


def test_load_minimums_rejects_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(gate.GateError, match="cannot read"):
        gate.load_minimums(tmp_path / "pyproject.toml")


@pytest.mark.parametrize(
    "toml",
    [
        pytest.param("not = [valid", id="broken-toml"),
        pytest.param("[tool.other]\nkey = 1\n", id="table-missing"),
        pytest.param(
            "[tool.coverage_gate]\nstatements = 98\nbranches = 94\n", id="key-missing"
        ),
        pytest.param(MINIMUMS_TOML + "statments = 1\n", id="misspelled-extra-key"),
        pytest.param(
            "[tool.coverage_gate]\nstatements = 101\nbranches = 94\nfunctions = 98\n",
            id="above-100",
        ),
    ],
)
def test_load_minimums_rejects_an_invalid_table(tmp_path: Path, toml: str) -> None:
    path = tmp_path / "pyproject.toml"
    path.write_text(toml)

    with pytest.raises(gate.GateError, match="coverage_gate"):
        gate.load_minimums(path)


def test_the_committed_minimums_are_valid() -> None:
    minimums = gate.load_minimums(gate.PYPROJECT_PATH)

    assert minimums.statements >= 90
    assert minimums.branches >= 90
    assert minimums.functions >= 90


def test_main_passes_and_prints_every_metric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path, pyproject_path = _write_inputs(tmp_path, _report())

    assert gate.main(report_path, pyproject_path) == 0
    assert capsys.readouterr().out == (
        "check_coverage_gate: OK - statements 100.00% (minimum 98.00%), "
        "branches 100.00% (minimum 94.00%), functions 100.00% (minimum 98.00%)\n"
    )


def test_main_fails_and_lists_the_shortfall(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path, pyproject_path = _write_inputs(tmp_path, _report(branches=(100, 90)))

    assert gate.main(report_path, pyproject_path) == 1
    assert "branches: 90.00% is below the minimum of 94.00%" in capsys.readouterr().out


def test_main_fails_when_the_report_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, pyproject_path = _write_inputs(tmp_path, _report())

    assert gate.main(tmp_path / "absent.json", pyproject_path) == 1
    assert "check_coverage_gate: FAILED - cannot read" in capsys.readouterr().out


def test_main_fails_when_the_minimums_are_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path, _ = _write_inputs(tmp_path, _report())

    assert gate.main(report_path, tmp_path / "absent.toml") == 1
    assert "check_coverage_gate: FAILED - cannot read" in capsys.readouterr().out
