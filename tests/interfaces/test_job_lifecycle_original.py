"""Keep every original job start, overlap rule and phase decision unchanged."""

import json
from collections.abc import Callable
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest
from fastapi import HTTPException

from spotify_manager import api
from tests.support.effects import Json
from tests.support.job_baseline import CASES
from tests.support.job_baseline import STATUSES
from tests.support.job_baseline import Family
from tests.support.job_baseline import JobStatus
from tests.support.job_baseline import StartCase
from tests.support.job_baseline import ThreadCapture
from tests.support.job_baseline import bind
from tests.support.job_baseline import conflict
from tests.support.job_baseline import pair_cases
from tests.support.job_baseline import queued
from tests.support.job_baseline import reset


FIXTURE = Path(__file__).parents[1] / "fixtures/refactor/job_lifecycle_original.json"
PLAYLIST_QUERIES: dict[str, Callable[[], list[api.BlastJobResult]]] = {
    "blast": api.cmd_active_blast_jobs,
    "dormant": api.cmd_active_blast_artist_jobs,
    "daily": api.cmd_active_daily_mind_radio_jobs,
    "found": api.cmd_active_found_art_jobs,
    "sauvignon": api.cmd_active_sauvignon_jobs,
    "queue-fill": api.cmd_active_queue_fill_jobs,
    "queue-flush": api.cmd_active_queue_flush_jobs,
    "new-kids": api.cmd_active_new_kids_jobs,
    "queue2": api.cmd_active_queue_2_jobs,
    "queue3": api.cmd_active_queue_3_jobs,
    "queue3-import": api.cmd_active_queue_3_jobs,
    "new-wine": api.cmd_active_new_wine_jobs,
    "slow": api.cmd_active_slow_listening_jobs,
    "old": api.cmd_active_something_old_jobs,
    "releases": api.cmd_active_release_check_jobs,
    "discography": api.cmd_active_discography_jobs,
    "requeue": api.cmd_active_requeue_for_a_dream_jobs,
    "palace": api.cmd_active_palace_of_memory_jobs,
    "palace-cursor": api.cmd_active_palace_of_memory_jobs,
    "history": api.cmd_active_scrobble_history_jobs,
    "annual": api.cmd_active_new_year_jobs,
}


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    """Own synthetic job handles without leaving state for another test.

    Yields:
        Control to the isolated job observation.
    """
    reset()
    yield
    reset()


@pytest.fixture(scope="module")
def baseline() -> dict[str, Json]:
    """Read immutable observations captured from the Item 6 merge.

    Returns:
        Complete original job protocol tables.
    """
    return cast(dict[str, Json], json.loads(FIXTURE.read_text()))


def _table(baseline: dict[str, Json], name: str) -> dict[str, Json]:
    table = baseline[name]
    assert isinstance(table, dict)
    return table


def _case_name(case: StartCase) -> str:
    return case.name


def _pair_names() -> list[str]:
    result = []
    for first, second in pair_cases():
        result.append(f"{first.name}:{second.name}")
    return result


@pytest.mark.parametrize("case", CASES, ids=_case_name)
def test_complete_queued_snapshot_and_dispatch(
    case: StartCase, baseline: dict[str, Json]
) -> None:
    """Preserve detached wire fields, queued log and ordered worker arguments.

    Args:
        case: Original configured adapter.
        baseline: Immutable original observations.
    """
    assert queued(case) == _table(baseline, "starts")[case.name]


@pytest.mark.parametrize(("first", "second"), pair_cases(), ids=_pair_names())
def test_original_directed_overlap_matrix(
    first: StartCase, second: StartCase, baseline: dict[str, Json]
) -> None:
    """Retain exact conflicts and accepted overlaps across both registries.

    Args:
        first: Original job registered first.
        second: Original requested subsequent adapter.
        baseline: Immutable original overlap outcomes.
    """
    identity = f"{first.name}:{second.name}"
    assert conflict(first, second, "running") == _table(baseline, "pairs")[identity]


@pytest.mark.parametrize("case", CASES, ids=_case_name)
@pytest.mark.parametrize("status", STATUSES)
def test_original_phase_blocks_or_releases_start(
    case: StartCase, status: JobStatus, baseline: dict[str, Json]
) -> None:
    """Preserve the original distinction between active and terminal phases.

    Args:
        case: Original start adapter.
        status: Existing handle's observed phase.
        baseline: Immutable original phase outcomes.
    """
    identity = f"{case.name}:{status}"
    assert conflict(case, case, status) == _table(baseline, "phases")[identity]


def _active_snapshots(
    case: StartCase,
) -> list[api.AnalysisJobResult | api.BlastJobResult]:
    result: list[api.AnalysisJobResult | api.BlastJobResult] = []
    if case.family == "analysis":
        result.extend(api.cmd_active_library_analysis_jobs())
        return result
    result.extend(PLAYLIST_QUERIES[case.name]())
    return result


def _original_snapshot(baseline: dict[str, Json], case: StartCase) -> dict[str, Json]:
    observation = _table(baseline, "starts")[case.name]
    assert isinstance(observation, dict)
    snapshot = observation["snapshot"]
    assert isinstance(snapshot, dict)
    return snapshot.copy()


@pytest.mark.parametrize("case", CASES, ids=_case_name)
@pytest.mark.parametrize("status", STATUSES)
def test_polling_preserves_original_phase_and_detached_view(
    case: StartCase,
    status: JobStatus,
    baseline: dict[str, Json],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use frozen original phase decisions to check every adapter's polling view.

    Args:
        case: Configured original analysis or playlist/history adapter.
        status: Phase exposed by the original process-local handle.
        baseline: Original queued wire view and active-phase decisions.
        monkeypatch: Deterministic dispatch and identity boundaries.
    """
    bind(monkeypatch)
    case.start()
    observed = _results(case.family)[0]
    observed.status = status
    decision = _table(baseline, "phases")[f"{case.name}:{status}"]
    assert isinstance(decision, dict)
    views = _active_snapshots(case)
    if decision["status_code"] != 409:
        assert views == []
        return
    expected = _original_snapshot(baseline, case)
    expected["status"] = status
    assert [view.model_dump(mode="json") for view in views] == [expected]
    count = len(observed.logs)
    views[0].logs.append(
        api.AnalysisJobLog(sequence=999, timestamp="test", message="test")
    )
    assert len(observed.logs) == count


class FailedDispatch(ThreadCapture):
    """Fail the scheduler after the original registry has accepted its handle."""

    def start(self) -> None:
        """Expose an original thread-start failure without running the worker.

        Raises:
            RuntimeError: Dispatch is unavailable after reservation.
        """
        raise RuntimeError("dispatcher unavailable")


@pytest.mark.parametrize("case", CASES, ids=_case_name)
def test_dispatch_failure_retains_original_queued_handle(
    case: StartCase, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Protect the original orphaned-queued failure contract from silent repair.

    Args:
        case: Original configured adapter.
        monkeypatch: Scoped scheduler and deterministic identity replacements.
    """
    bind(monkeypatch)
    monkeypatch.setattr(api, "Thread", FailedDispatch)
    with pytest.raises(RuntimeError, match="dispatcher unavailable"):
        case.start()
    results = _results(case.family)
    assert len(results) == 1
    assert results[0].status == "queued"


def _results(family: Family) -> list[api.AnalysisJobResult | api.BlastJobResult]:
    results: list[api.AnalysisJobResult | api.BlastJobResult] = []
    if family == "analysis":
        for analysis in api._analysis_jobs.values():
            results.append(analysis.result)
        return results
    for playlist in api._blast_jobs.values():
        results.append(playlist.result)
    return results


def _concurrent_start(case: StartCase, barrier: Barrier) -> int:
    barrier.wait(timeout=5)
    try:
        case.start()
    except HTTPException as error:
        return error.status_code
    return 202


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    (
        (CASES[0], CASES[0], [202, 409]),
        (CASES[0], CASES[1], [202, 202]),
        (CASES[6], CASES[-1], [202, 409]),
        (CASES[0], CASES[6], [202, 202]),
    ),
    ids=(
        "same-analysis",
        "different-analyses",
        "playlist-annual",
        "separate-registries",
    ),
)
def test_concurrent_reservations_preserve_original_conflict_scope(
    first: StartCase,
    second: StartCase,
    expected: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Race two starts using real threads and a deterministic rendezvous.

    Args:
        first: First competing adapter.
        second: Second competing adapter.
        expected: Original unordered accepted/conflicting outcomes.
        monkeypatch: Scoped worker replacement; scheduling threads stay real.
    """
    bind(monkeypatch)
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as workers:
        left = workers.submit(_concurrent_start, first, barrier)
        right = workers.submit(_concurrent_start, second, barrier)
        observed = sorted((left.result(timeout=10), right.result(timeout=10)))
    assert observed == expected
    assert len(ThreadCapture.observations) == expected.count(202)
