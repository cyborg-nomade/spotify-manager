"""Enforce the approved statement and branch floors as separate measurements."""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict
from typing import cast


ROOT = Path(__file__).resolve().parents[2]


class CoverageCounts(TypedDict):
    """Describe the coverage.py counters used by the independent gates.

    Args:
        covered_lines: Executed statements.
        num_statements: Measured statements.
        covered_branches: Executed branches.
        num_branches: Measured branches.
    """

    covered_lines: int
    num_statements: int
    covered_branches: int
    num_branches: int


class FileCoverage(TypedDict):
    """Read one module's coverage summary.

    Args:
        summary: Counters from the unmodified coverage.py report.
    """

    summary: CoverageCounts


class CoverageMetadata(TypedDict):
    """Require coverage to have measured branches.

    Args:
        branch_coverage: Whether branch instrumentation was enabled.
    """

    branch_coverage: bool


class CoverageReport(TypedDict):
    """Name the consumed coverage.py JSON fields without a runtime dependency.

    Args:
        meta: Instrumentation mode.
        files: Complete measured source inventory and counters.
    """

    meta: CoverageMetadata
    files: dict[str, FileCoverage]


@dataclass(frozen=True)
class CoverageFloor:
    """Keep the approved independent floors beside their source scope.

    Args:
        prefix: Repository-relative source directory, including its trailing slash.
        statements: Required statement percentage.
        branches: Required branch percentage.
    """

    prefix: str
    statements: int
    branches: int


FLOORS = (
    CoverageFloor("spotify_manager/", 95, 90),
    CoverageFloor("spotify_manager/domain/", 98, 95),
    CoverageFloor("spotify_manager/application/", 98, 95),
)


def coverage_failures(report: CoverageReport, root: Path) -> list[str]:
    """Reject missing measurements and each independently failing coverage floor.

    Args:
        report: Original coverage.py JSON report.
        root: Repository root whose complete package must be represented.

    Returns:
        Actionable failures; an empty list means every gate passed.
    """
    failures = []
    if not report["meta"]["branch_coverage"]:
        failures.append(
            "Branch coverage was not measured; run pytest with --cov-branch."
        )
    sources = _source_paths(root)
    for name in sorted(sources - report["files"].keys()):
        failures.append(f"Unmeasured source: {name}")
    for name in sorted(report["files"].keys() - sources):
        if name.startswith("spotify_manager/"):
            failures.append(f"Unknown measured source: {name}")
    for floor in FLOORS:
        counts = _counts(report, floor.prefix)
        failures.extend(_below_floor(counts, floor))
    return failures


def _source_paths(root: Path) -> set[str]:
    sources = set()
    for path in (root / "spotify_manager").rglob("*.py"):
        sources.add(path.relative_to(root).as_posix())
    return sources


def _counts(report: CoverageReport, prefix: str) -> CoverageCounts:
    counts: CoverageCounts = {
        "covered_lines": 0,
        "num_statements": 0,
        "covered_branches": 0,
        "num_branches": 0,
    }
    for name, measured in report["files"].items():
        if name.startswith(prefix):
            _add_counts(counts, measured["summary"])
    return counts


def _add_counts(total: CoverageCounts, current: CoverageCounts) -> None:
    total["covered_lines"] += current["covered_lines"]
    total["num_statements"] += current["num_statements"]
    total["covered_branches"] += current["covered_branches"]
    total["num_branches"] += current["num_branches"]


def _below_floor(counts: CoverageCounts, floor: CoverageFloor) -> list[str]:
    failures = []
    if not counts["num_statements"]:
        return [f"No statements measured in {floor.prefix}"]
    if counts["covered_lines"] * 100 < counts["num_statements"] * floor.statements:
        failures.append(f"{floor.prefix}: statements below {floor.statements}%")
    if counts["covered_branches"] * 100 < counts["num_branches"] * floor.branches:
        failures.append(f"{floor.prefix}: branches below {floor.branches}%")
    return failures


def main() -> int:
    """Check a full-suite JSON report independently of combined coverage scores.

    Returns:
        Zero when all independent floors pass, otherwise one.

    Raises:
        OSError: The report cannot be read.
        ValueError: The report is not valid JSON.
        KeyError: Required coverage.py report fields are absent.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    arguments = parser.parse_args()
    report = cast(CoverageReport, json.loads(arguments.report.read_text()))
    failures = coverage_failures(report, ROOT)
    for failure in failures:
        print(failure)
    if failures:
        return 1
    print("Coverage passed: package 95%/90%; domain and application each 98%/95%.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
