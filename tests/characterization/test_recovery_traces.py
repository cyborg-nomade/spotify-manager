"""Independent pre-migration evidence for album recovery and accepted effects."""

import json
from datetime import date
from functools import partial
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager import loaders_savers
from spotify_manager.core.library_data.runtime import reset_library_data_service
from spotify_manager.core.state.runtime import reset_state_service
from spotify_manager.routines import recover_removed_albums as recovery
from tests.characterization.scenarios import Scenario
from tests.characterization.test_routine_traces import capture
from tests.routines.test_recover_removed_albums import FakeSpotify
from tests.routines.test_recover_removed_albums import _stats_report
from tests.support.effects import Fault
from tests.support.effects import Phase
from tests.support.effects import Trace
from tests.support.effects import TraceAssertion


BOUNDARIES = [
    ("spotify.user_follow_artists", 1),
    ("spotify.current_user_saved_albums_add", 1),
    ("mirror.save_total_artists_file", 1),
    ("mirror.save_total_albums_new_file", 1),
    ("mirror.save_stats_history", 1),
    ("audit", 1),
    ("audit", 2),
    ("checkpoint", 1),
    ("checkpoint", 2),
]


def _files(patch: pytest.MonkeyPatch, root: Path) -> None:
    records = [
        {
            "spotify_id": "future",
            "album": "Tomorrow's Record",
            "artist": "Primary Artist",
        },
        {"spotify_id": "absent", "album": "Unavailable", "artist": "Unknown"},
    ]
    lines = [json.dumps(record) for record in records]
    (root / "removed.jsonl").write_text("\n".join(lines) + "\n")
    files: tuple[tuple[str, str, object], ...] = (
        ("TOTAL_ALBUMS_NEW_PATH", "albums.json", []),
        ("TOTAL_ARTISTS_PATH", "artists.json", []),
        (
            "STATS_HISTORY_PATH",
            "stats.json",
            {"2026.09.24": _stats_report().model_dump()},
        ),
    )
    for name, filename, contents in files:
        path = root / filename
        path.write_text(json.dumps(contents))
        patch.setattr(loaders_savers, name, path)


def _remote(spotify: FakeSpotify) -> dict[str, object]:
    return {"followed": spotify.followed_artist_ids, "saved": spotify.saved_album_ids}


def _watch_recovery(
    patch: pytest.MonkeyPatch, trace: Trace, spotify: FakeSpotify
) -> None:
    for name in (
        "albums",
        "current_user_following_artists",
        "user_follow_artists",
        "current_user_saved_albums_contains",
        "current_user_saved_albums_add",
    ):
        trace.watch(patch, spotify, name, f"spotify.{name}")
    for name in (
        "save_total_artists_file",
        "save_total_albums_new_file",
        "save_stats_history",
    ):
        trace.watch(patch, recovery, name, f"mirror.{name}")
    trace.watch(patch, recovery, "append_recovery_events", "audit")
    trace.watch(patch, recovery, "_save_log_state", "checkpoint")


def _scenario(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    _files(patch, root)
    spotify = FakeSpotify()
    _watch_recovery(patch, trace, spotify)
    operation = partial(
        recovery.recover_removed_albums,
        cast(Spotify, spotify),
        echo=partial(trace.record, "echo", "message"),
        removal_log_path=root / "removed.jsonl",
        recovery_log_path=root / "recovery.jsonl",
        today=date(2026, 7, 14),
    )
    return Scenario(operation, partial(_remote, spotify))


@pytest.mark.parametrize("dry_run", [False, True])
def test_recovery_complete_trace(
    dry_run: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assert_trace: TraceAssertion,
) -> None:
    """Compare recovery results, remote effects, and persisted artifacts.

    Args:
        dry_run: Whether to preview the recovery.
        monkeypatch: Per-test dependency overrides.
        tmp_path: Isolated fixture files.
        assert_trace: Independent pre-migration recording comparator.
    """
    trace = Trace(tmp_path)
    capture(trace, _scenario(monkeypatch, tmp_path, trace), tmp_path, dry_run)
    assert not any(
        event["operation"] == "run" and event["phase"] == "error"
        for event in trace.events
    )
    assert_trace(f"recovery-{'dry' if dry_run else 'normal'}", trace.events)


@pytest.mark.parametrize("operation,occurrence", BOUNDARIES)
@pytest.mark.parametrize("phase", ["before", "after"])
def test_recovery_restart_trace(
    operation: str,
    occurrence: int,
    phase: Phase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assert_trace: TraceAssertion,
) -> None:
    """Retain partial writes and restart behavior at each durable boundary.

    Args:
        operation: Effect boundary to interrupt.
        occurrence: One-based effect occurrence.
        phase: Whether the effect was accepted before interruption.
        monkeypatch: Per-test dependency overrides.
        tmp_path: Isolated fixture files.
        assert_trace: Independent pre-migration recording comparator.
    """
    trace = Trace(tmp_path, Fault(operation, phase, occurrence))
    scenario = _scenario(monkeypatch, tmp_path, trace)
    capture(trace, scenario, tmp_path, False)
    assert trace.fired
    reset_state_service()
    reset_library_data_service()
    trace.record("process", "restart")
    capture(trace, scenario, tmp_path, False)
    assert_trace(f"recovery-{operation}-{occurrence}-{phase}", trace.events)
