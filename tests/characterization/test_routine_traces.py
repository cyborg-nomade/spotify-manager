"""Freeze results, prompts, ordered effects, and restart behavior of each family."""

import gzip
import json
from functools import partial
from pathlib import Path

import pytest

from spotify_manager.core.library_data.runtime import reset_library_data_service
from spotify_manager.core.state.runtime import reset_state_service
from tests.characterization.scenarios import FACTORIES
from tests.characterization.scenarios import Scenario
from tests.support.effects import Fault
from tests.support.effects import Json
from tests.support.effects import Phase
from tests.support.effects import Trace
from tests.support.effects import TraceAssertion


# Each boundary has both a rejected operation and an accepted-but-lost response.
BOUNDARIES = {
    "album": ("spotify.album_tracks", "spotify.contains"),
    "requeue": ("spotify._post", "spotify._delete", "audit"),
    "slow": ("spotify._post", "spotify._delete", "checkpoint", "audit"),
    "wine": ("spotify._post", "spotify._delete", "checkpoint", "audit"),
    "kids": ("spotify._post", "spotify._delete", "checkpoint", "audit"),
    "queue": ("spotify._post", "spotify._delete", "checkpoint", "audit"),
    "history": ("lastfm.read", "mirror", "audit"),
    "palace": ("spotify._post", "checkpoint", "audit"),
    "analysis": ("checkpoint", "mirror", "audit", "spotify.current_user_saved_tracks"),
    "review": (
        "spotify.user_follow_artists",
        "spotify.current_user_saved_albums_delete",
        "prompt",
        "mirror.save_total_albums_new_file",
        "audit",
    ),
    "upload": ("hub.list", "hub.commit"),
    "release": ("checkpoint", "spotify._post", "audit"),
}


def _read_artifact(path: Path) -> Json:
    contents = path.read_bytes()
    if path.suffix == ".gz":
        contents = gzip.decompress(contents)
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in contents.splitlines()]
    return json.loads(contents)


def artifacts(root: Path) -> dict[str, Json]:
    """Read a scenario's JSON, JSONL, and compressed JSON artifacts.

    Args:
        root: Directory containing only the scenario's temporary files.

    Returns:
        Parsed contents keyed by relative file name.

    Raises:
        OSError: A file cannot be read or decompressed.
        ValueError: An artifact contains invalid JSON.
    """
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[str(path.relative_to(root))] = _read_artifact(path)
    return result


def capture(trace: Trace, scenario: Scenario, root: Path, dry_run: bool) -> None:
    """Record a routine outcome followed by its remote and persisted state.

    Args:
        trace: Recorder receiving the result and snapshots.
        scenario: Invocation and remote state to observe.
        root: Temporary artifact directory.
        dry_run: Whether to request the routine's preview mode.

    Raises:
        OSError: An artifact cannot be read.
        ValueError: An artifact contains invalid JSON.
        AssertionError: A fixture or unexpected interaction fails.
    """
    trace.invoke(partial(scenario.run, dry_run))
    trace.record("remote", "snapshot", scenario.remote())
    trace.record("files", "snapshot", artifacts(root))


def _normal_cases() -> list[tuple[str, bool]]:
    cases = [(name, False) for name in FACTORIES]
    for name in FACTORIES:
        if name not in {"album", "review", "analysis"}:
            cases.append((name, True))
    return cases


def _interruption_cases() -> list[tuple[str, str, int]]:
    cases = []
    for name, operations in BOUNDARIES.items():
        for operation in operations:
            cases.append((name, operation, 1))
    for name in ("slow", "wine", "kids", "queue"):
        for occurrence in (2, 3, 4):
            cases.append((name, "checkpoint", occurrence))
    cases.append(("analysis", "spotify.current_user_saved_tracks", 2))
    return cases


def _assert_success(trace: Trace) -> None:
    for event in trace.events:
        assert (event["operation"], event["phase"]) != ("run", "error"), trace.events


@pytest.mark.parametrize("name,dry_run", _normal_cases())
def test_normal_and_dry_run_contract(
    name: str,
    dry_run: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assert_trace: TraceAssertion,
) -> None:
    """Preserve each routine's result, effects, prompts, and artifact contents.

    Args:
        name: Scenario family.
        dry_run: Whether this case requests preview mode.
        monkeypatch: Per-test patch manager.
        tmp_path: Temporary artifact directory.
        assert_trace: Comparison against the reviewed golden recording.
    """
    trace = Trace(tmp_path)
    scenario = FACTORIES[name](monkeypatch, tmp_path, trace)
    assert not dry_run or scenario.supports_dry_run
    capture(trace, scenario, tmp_path, dry_run)
    _assert_success(trace)
    assert_trace(f"{name}-{'dry' if dry_run else 'normal'}", trace.events)


@pytest.mark.parametrize("name,operation,occurrence", _interruption_cases())
@pytest.mark.parametrize("phase", ["before", "after"])
def test_interruption_and_restart_contract(
    name: str,
    operation: str,
    occurrence: int,
    phase: Phase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assert_trace: TraceAssertion,
) -> None:
    """Preserve recovery when an effect fails before or after acceptance.

    Args:
        name: Scenario family.
        operation: Effect boundary to interrupt.
        occurrence: One-based invocation to interrupt.
        phase: Whether interruption precedes or follows acceptance.
        monkeypatch: Per-test patch manager.
        tmp_path: Temporary artifact directory.
        assert_trace: Comparison against the reviewed golden recording.
    """
    trace = Trace(tmp_path, Fault(operation, phase, occurrence))
    scenario = FACTORIES[name](monkeypatch, tmp_path, trace)
    capture(trace, scenario, tmp_path, False)
    assert trace.fired, f"Scenario never reached {operation}"
    # Re-enter with the same remote/files, but no process-local service cache.
    reset_state_service()
    reset_library_data_service()
    trace.record("process", "restart")
    capture(trace, scenario, tmp_path, False)
    assert_trace(f"{name}-{operation}-{occurrence}-{phase}", trace.events)
