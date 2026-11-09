#!/usr/bin/env python3
"""Holds the measured test coverage to separate minimums per metric.

pytest-cov's single --cov-fail-under value mixes statements and branches into
one number, so a large well-tested area can hide a drop in another metric.
This gate reads the JSON report written by pytest (--cov-report=json) and
compares statements, branches and functions with the minimums configured
under [tool.coverage_gate] in pyproject.toml.

A function counts as covered when at least one of its statements ran;
functions without statements (stubs, bare docstrings) are not counted.

Usage:
    python scripts/check_coverage_gate.py
"""

import sys
import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / "coverage.json"
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"


class GateError(Exception):
    """The gate cannot be evaluated (missing, unreadable or incomplete input)."""


class GateMinimums(BaseModel):
    """Minimum percentages from [tool.coverage_gate]; a typo in the table fails."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statements: float = Field(ge=0, le=100)
    branches: float = Field(ge=0, le=100)
    functions: float = Field(ge=0, le=100)


# The models below read files written by other tools (coverage.py, TOML), so
# unknown keys are ignored on purpose: only the fields the gate needs matter.
class _Tools(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    coverage_gate: GateMinimums


class _Pyproject(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    tool: _Tools


class _Meta(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    branch_coverage: bool


class _Totals(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    num_statements: int
    covered_lines: int
    num_branches: int
    covered_branches: int


class _FunctionSummary(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    num_statements: int
    covered_lines: int


class _Function(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    summary: _FunctionSummary


class _File(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    functions: dict[str, _Function]


class _CoverageReport(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    meta: _Meta
    totals: _Totals
    files: dict[str, _File]


class Measured(BaseModel):
    """Measured percentages, in the same shape as the configured minimums."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statements: float
    branches: float
    functions: float


def _percent(covered: int, total: int) -> float:
    return 100.0 if total == 0 else 100.0 * covered / total


def _function_summaries(report: _CoverageReport) -> list[_FunctionSummary]:
    """Summaries of all named functions that contain at least one statement.

    The empty name is the module level, which is covered by the statements metric.
    """
    return [
        function.summary
        for file in report.files.values()
        for name, function in file.functions.items()
        if name and function.summary.num_statements > 0
    ]


def measure(report: _CoverageReport) -> Measured:
    functions = _function_summaries(report)
    totals = report.totals
    return Measured(
        statements=_percent(totals.covered_lines, totals.num_statements),
        branches=_percent(totals.covered_branches, totals.num_branches),
        functions=_percent(
            sum(1 for function in functions if function.covered_lines > 0),
            len(functions),
        ),
    )


def _by_metric(values: Measured | GateMinimums) -> dict[str, float]:
    return {
        "statements": values.statements,
        "branches": values.branches,
        "functions": values.functions,
    }


def find_shortfalls(measured: Measured, minimums: GateMinimums) -> list[str]:
    required = _by_metric(minimums)
    return [
        f"{metric}: {value:.2f}% is below the minimum of {required[metric]:.2f}%"
        for metric, value in _by_metric(measured).items()
        if value < required[metric]
    ]


def load_report(path: Path) -> _CoverageReport:
    try:
        report = _CoverageReport.model_validate_json(path.read_text())
    except OSError as error:
        msg = f"cannot read {path} ({error}); run pytest first to write the report"
        raise GateError(msg) from error
    except ValidationError as error:
        msg = f"{path} is not a coverage.py JSON report: {error}"
        raise GateError(msg) from error
    if not report.meta.branch_coverage:
        msg = (
            "the report holds no branch data; enable `branch = true` under "
            "[tool.coverage.run] so the branch minimum means something"
        )
        raise GateError(msg)
    return report


def load_minimums(path: Path) -> GateMinimums:
    try:
        pyproject = _Pyproject.model_validate(tomllib.loads(path.read_text()))
    except OSError as error:
        msg = f"cannot read {path} ({error})"
        raise GateError(msg) from error
    except (tomllib.TOMLDecodeError, ValidationError) as error:
        msg = f"{path} has no valid [tool.coverage_gate] table: {error}"
        raise GateError(msg) from error
    return pyproject.tool.coverage_gate


def main(report_path: Path = REPORT_PATH, pyproject_path: Path = PYPROJECT_PATH) -> int:
    try:
        measured = measure(load_report(report_path))
        minimums = load_minimums(pyproject_path)
    except GateError as error:
        print(f"check_coverage_gate: FAILED - {error}")
        return 1

    shortfalls = find_shortfalls(measured, minimums)
    if not shortfalls:
        required = _by_metric(minimums)
        print(
            "check_coverage_gate: OK - "
            + ", ".join(
                f"{metric} {value:.2f}% (minimum {required[metric]:.2f}%)"
                for metric, value in _by_metric(measured).items()
            )
        )
        return 0

    print("check_coverage_gate: FAILED - coverage dropped below the minimums:")
    for shortfall in shortfalls:
        print(f"  {shortfall}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
