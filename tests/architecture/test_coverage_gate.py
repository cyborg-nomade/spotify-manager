"""Prove statement and branch floors cannot mask one another or omitted modules."""

import json
import sys
from pathlib import Path

import pytest

from tests.architecture import coverage_gate
from tests.architecture.coverage_gate import CoverageCounts
from tests.architecture.coverage_gate import CoverageReport
from tests.architecture.coverage_gate import FileCoverage
from tests.architecture.coverage_gate import coverage_failures


def _report(root: Path, statements: int = 100, branches: int = 100) -> CoverageReport:
    files: dict[str, FileCoverage] = {}
    for name in ("adapter.py", "domain/policy.py", "application/use_case.py"):
        path = root / "spotify_manager" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("value = 1\n")
        counts: CoverageCounts = {
            "covered_lines": statements,
            "num_statements": 100,
            "covered_branches": branches,
            "num_branches": 100,
        }
        files[path.relative_to(root).as_posix()] = {"summary": counts}
    return {"meta": {"branch_coverage": True}, "files": files}


def test_coverage_passes_at_the_exact_independent_floors(tmp_path: Path) -> None:
    """Use exact counters rather than rounded display or combined percentages.

    Args:
        tmp_path: Complete synthetic package and measurements.
    """
    report = _report(tmp_path)
    for name in ("domain/policy.py", "application/use_case.py"):
        counts = report["files"]["spotify_manager/" + name]["summary"]
        counts["covered_lines"] = 98
        counts["covered_branches"] = 95
    report["files"]["spotify_manager/adapter.py"]["summary"]["covered_lines"] = 89
    report["files"]["spotify_manager/adapter.py"]["summary"]["covered_branches"] = 80
    assert coverage_failures(report, tmp_path) == []


@pytest.mark.parametrize("statements,branches", [(94, 100), (100, 89)])
def test_package_metrics_cannot_hide_one_another(
    tmp_path: Path, statements: int, branches: int
) -> None:
    """A high combined score must still fail a deficient independent metric.

    Args:
        tmp_path: Disposable package.
        statements: Covered statement count out of 100.
        branches: Covered branch count out of 100.
    """
    failures = coverage_failures(_report(tmp_path, statements, branches), tmp_path)
    assert any(message.startswith("spotify_manager/:") for message in failures)


@pytest.mark.parametrize("layer", ["domain", "application"])
@pytest.mark.parametrize(
    "metric,covered", [("covered_lines", 97), ("covered_branches", 94)]
)
def test_each_business_layer_has_its_own_floor(
    tmp_path: Path, layer: str, metric: str, covered: int
) -> None:
    """A fully covered outer layer cannot mask insufficient business coverage.

    Args:
        tmp_path: Disposable package.
        layer: Business package with the deficient metric.
        metric: Counter reduced below its approved floor.
        covered: Exact deficient count out of 100.
    """
    report = _report(tmp_path)
    filename = "policy.py" if layer == "domain" else "use_case.py"
    counts = report["files"][f"spotify_manager/{layer}/{filename}"]["summary"]
    if metric == "covered_lines":
        counts["covered_lines"] = covered
    else:
        counts["covered_branches"] = covered
    failures = coverage_failures(report, tmp_path)
    assert len(failures) == 1
    assert failures[0].startswith(f"spotify_manager/{layer}/:")


def test_rejects_missing_branch_instrumentation_and_omitted_source(
    tmp_path: Path,
) -> None:
    """An omitted module or a statement-only run must fail even at 100%.

    Args:
        tmp_path: Disposable complete source tree.
    """
    report = _report(tmp_path)
    report["meta"]["branch_coverage"] = False
    del report["files"]["spotify_manager/domain/policy.py"]
    failures = coverage_failures(report, tmp_path)
    assert len(failures) == 3
    assert "Branch coverage was not measured" in failures[0]
    assert "Unmeasured source: spotify_manager/domain/policy.py" in failures[1]
    assert failures[2] == "No statements measured in spotify_manager/domain/"


def test_no_branches_is_a_valid_measurement_for_a_straight_line_module(
    tmp_path: Path,
) -> None:
    """Do not invent a failing percentage when a measured layer has no branches.

    Args:
        tmp_path: Disposable package with branch instrumentation enabled.
    """
    report = _report(tmp_path)
    for measured in report["files"].values():
        measured["summary"]["num_branches"] = 0
        measured["summary"]["covered_branches"] = 0
    assert coverage_failures(report, tmp_path) == []


def test_stale_deleted_modules_cannot_inflate_coverage(tmp_path: Path) -> None:
    """Reject counters from source files that are no longer in the package.

    Args:
        tmp_path: Disposable package and its original complete report.
    """
    report = _report(tmp_path)
    report["files"]["spotify_manager/deleted.py"] = report["files"][
        "spotify_manager/adapter.py"
    ]
    assert coverage_failures(report, tmp_path) == [
        "Unknown measured source: spotify_manager/deleted.py"
    ]


@pytest.mark.parametrize("statements,expected", [(100, 0), (94, 1)])
def test_command_reports_failure_with_a_nonzero_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    statements: int,
    expected: int,
) -> None:
    """Keep the exact command used by CI actionable and fail-closed.

    Args:
        tmp_path: Synthetic report and source tree.
        monkeypatch: Scope command arguments and source inventory to the test.
        capsys: Captured operator-facing result.
        statements: Covered statements out of 100.
        expected: Required process result.
    """
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(_report(tmp_path, statements)))
    monkeypatch.setattr(coverage_gate, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["coverage_gate", str(path)])
    assert coverage_gate.main() == expected
    assert capsys.readouterr().out
