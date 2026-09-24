"""Freeze results, prompts, ordered effects, and restart behavior of each family."""

import gzip
import json
from pathlib import Path

import pytest

from spotify_manager.core.library_data.runtime import reset_library_data_service
from spotify_manager.core.state.runtime import reset_state_service
from tests.characterization.scenarios import FACTORIES
from tests.support.effects import Fault
from tests.support.effects import Trace


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


def artifacts(root: Path):
    result = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        contents = path.read_bytes()
        if path.suffix == ".gz":
            contents = gzip.decompress(contents)
        if path.suffix == ".jsonl":
            result[str(path.relative_to(root))] = [
                json.loads(line) for line in contents.splitlines()
            ]
        else:
            result[str(path.relative_to(root))] = json.loads(contents)
    return result


def capture(trace, scenario, root, dry_run):
    trace.invoke(lambda: scenario.run(dry_run))
    trace.record("remote", "snapshot", scenario.remote())
    trace.record("files", "snapshot", artifacts(root))


@pytest.mark.parametrize(
    "name,dry_run",
    [(name, False) for name in FACTORIES]
    + [
        (name, True)
        for name in FACTORIES
        if name not in {"album", "review", "analysis"}
    ],
)
def test_normal_and_dry_run_contract(
    name, dry_run, monkeypatch, tmp_path, assert_trace
):
    trace = Trace(tmp_path)
    scenario = FACTORIES[name](monkeypatch, tmp_path, trace)
    assert not dry_run or scenario.supports_dry_run
    capture(trace, scenario, tmp_path, dry_run)
    assert not any(
        event["operation"] == "run" and event["phase"] == "error"
        for event in trace.events
    ), trace.events
    assert_trace(f"{name}-{'dry' if dry_run else 'normal'}", trace.events)


@pytest.mark.parametrize(
    "name,operation,occurrence",
    [
        (name, operation, 1)
        for name, operations in BOUNDARIES.items()
        for operation in operations
    ]
    + [
        (name, "checkpoint", occurrence)
        for name in ("slow", "wine", "kids", "queue")
        for occurrence in (2, 3, 4)
    ]
    + [("analysis", "spotify.current_user_saved_tracks", 2)],
)
@pytest.mark.parametrize("phase", ["before", "after"])
def test_interruption_and_restart_contract(
    name, operation, occurrence, phase, monkeypatch, tmp_path, assert_trace
):
    trace = Trace(tmp_path, Fault(operation, phase, occurrence))
    scenario = FACTORIES[name](monkeypatch, tmp_path, trace)
    capture(trace, scenario, tmp_path, False)
    assert trace.fired, f"Scenario never reached {operation}"
    # Re-enter with the same remote/files, but no process-local state-service cache.
    reset_state_service()
    reset_library_data_service()
    trace.record("process", "restart")
    capture(trace, scenario, tmp_path, False)
    assert_trace(f"{name}-{operation}-{occurrence}-{phase}", trace.events)
