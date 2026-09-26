"""Pre-migration refill evidence for pending transfers and eligibility reads."""

import json
from functools import partial
from pathlib import Path
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.core.state.runtime import reset_state_service
from spotify_manager.routines import new_wine
from tests.characterization.scenarios import Scenario
from tests.characterization.scenarios import effects
from tests.characterization.test_routine_traces import capture
from tests.routines.test_new_wine import FakeSpotify
from tests.routines.test_new_wine import raw_release
from tests.routines.test_new_wine import raw_track
from tests.support.effects import Fault
from tests.support.effects import Phase
from tests.support.effects import Trace
from tests.support.effects import TraceAssertion


BOUNDARIES = [
    ("spotify._post", 1),
    ("spotify._delete", 1),
    ("audit", 1),
    ("audit", 2),
    ("checkpoint", 1),
    ("checkpoint", 2),
    ("checkpoint", 3),
    ("checkpoint", 4),
]


def _files(root: Path) -> None:
    albums = []
    for index in range(3):
        albums.append(
            {
                "artist": "Rich",
                "album": f"Saved {index}",
                "uri": f"spotify:album:a{index}",
            }
        )
    (root / "albums.json").write_text(json.dumps(albums))
    (root / "liked.json").write_text(
        json.dumps(
            [
                {
                    "artist": "Low",
                    "album": "Low",
                    "track": "Stale",
                    "uri": "spotify:track:stale",
                }
            ]
        )
    )


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    release = raw_release("release", "Release", artist_id="artist", total_tracks=2)
    tracks = [
        raw_track("low", "Low", release, artist_id="low", artist_name="Low"),
        raw_track("rich", "Rich", release, artist_id="rich", artist_name="Rich"),
    ]
    spotify.playlists["cellar"] = tracks
    spotify.release_tracks["release"] = tracks
    spotify.saved_album_ids = {"a0", "a1", "a2"}
    return spotify


def _remote(spotify: FakeSpotify) -> dict[str, object]:
    return {"playlists": spotify.playlists, "mutations": spotify.mutations}


def _scenario(patch: pytest.MonkeyPatch, root: Path, trace: Trace) -> Scenario:
    _files(root)
    spotify = _spotify()
    effects(patch, trace, spotify, new_wine, audit="append_cellar_log")
    for name in (
        "current_user_saved_albums_contains",
        "current_user_saved_tracks_contains",
    ):
        trace.watch(patch, spotify, name, f"spotify.{name}")
    operation = partial(
        new_wine.flush_new_wine,
        cast(Spotify, spotify),
        "new",
        "sauv",
        trace.choices("choice"),
        wine_cellar_playlist_id="cellar",
        no_discovery=True,
        state_path=root / "state.json",
        log_path=root / "audit.jsonl",
        albums_path=root / "albums.json",
        liked_tracks_path=root / "liked.json",
        removed_albums_log_path=root / "removed.jsonl",
        year=2026,
        echo=partial(trace.record, "echo", "message"),
    )
    return Scenario(operation, partial(_remote, spotify))


@pytest.mark.parametrize("dry_run", [False, True])
def test_cellar_normal_trace(
    dry_run: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assert_trace: TraceAssertion,
) -> None:
    """Compare full refill effects, eligibility reads, state and preview audits.

    Args:
        dry_run: Whether to preview the transfer.
        monkeypatch: Scoped observation hooks.
        tmp_path: Isolated artifact directory.
        assert_trace: Pre-migration recording comparator.
    """
    trace = Trace(tmp_path)
    capture(trace, _scenario(monkeypatch, tmp_path, trace), tmp_path, dry_run)
    assert not any(event["phase"] == "error" for event in trace.events)
    assert_trace(f"cellar-{'dry' if dry_run else 'normal'}", trace.events)


@pytest.mark.parametrize("operation,occurrence", BOUNDARIES)
@pytest.mark.parametrize("phase", ["before", "after"])
def test_cellar_interruption_trace(
    operation: str,
    occurrence: int,
    phase: Phase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    assert_trace: TraceAssertion,
) -> None:
    """Preserve pending-transfer recovery before and after accepted effects.

    Args:
        operation: Effect to interrupt.
        occurrence: One-based effect occurrence.
        phase: Whether acceptance precedes failure.
        monkeypatch: Scoped observation hooks.
        tmp_path: Isolated artifact directory.
        assert_trace: Pre-migration recording comparator.
    """
    trace = Trace(tmp_path, Fault(operation, phase, occurrence))
    scenario = _scenario(monkeypatch, tmp_path, trace)
    capture(trace, scenario, tmp_path, False)
    assert trace.fired
    reset_state_service()
    trace.record("process", "restart")
    capture(trace, scenario, tmp_path, False)
    assert_trace(f"cellar-{operation}-{occurrence}-{phase}", trace.events)
