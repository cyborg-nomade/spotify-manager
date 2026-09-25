"""Prove the golden fixtures reject representative unsafe refactors."""

import json
import math
from collections.abc import Callable
from functools import partial
from pathlib import Path

import pytest
from spotipy import Spotify

from spotify_manager.processors import library_lookups
from spotify_manager.routines import new_wine
from spotify_manager.routines import requeue_for_a_dream
from tests.characterization.scenarios import FACTORIES
from tests.characterization.test_routine_traces import capture
from tests.support.effects import Trace


def _remove_first(
    original: Callable[
        [Spotify, str, new_wine.ReleaseTrack, requeue_for_a_dream.RetryCall], None
    ],
    spotify: Spotify,
    playlist_id: str,
    track: new_wine.ReleaseTrack,
    retry: requeue_for_a_dream.RetryCall,
) -> None:
    spotify._delete(
        f"playlists/{playlist_id}/items",
        payload={"items": [{"uri": "spotify:track:t1"}]},
    )
    original(spotify, playlist_id, track, retry)


def _ignore_audit(*args: object) -> None:
    pass


def _ignore_dry_run(
    original: Callable[..., object], *args: object, **kwargs: object
) -> object:
    kwargs["dry_run"] = False
    return original(*args, **kwargs)


def _install_regression(patch: pytest.MonkeyPatch, mutation: str) -> None:
    """Install one deliberately unsafe change without modifying source files.

    Args:
        patch: Per-test patch manager that restores the original implementation.
        mutation: One of the four regression names in the parametrized test.
    """
    if mutation == "ceil-threshold":
        patch.setattr(library_lookups, "floor", math.ceil)
        return
    if mutation == "missing-audit":
        patch.setattr(requeue_for_a_dream, "_append_log", _ignore_audit)
        return
    if mutation == "remove-first":
        replacement = partial(_remove_first, requeue_for_a_dream._add_track)
        patch.setattr(requeue_for_a_dream, "_add_track", replacement)
        return
    original = requeue_for_a_dream.flush_requeue_for_a_dream
    patch.setattr(
        requeue_for_a_dream,
        "flush_requeue_for_a_dream",
        partial(_ignore_dry_run, original),
    )


@pytest.mark.parametrize(
    "mutation",
    ["ceil-threshold", "remove-first", "missing-audit", "write-in-dry-run"],
)
def test_golden_contract_rejects_deliberate_regression(
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Ensure representative unsafe changes fail the normal parity assertion.

    Args:
        mutation: Deliberate change to a policy or effect boundary.
        monkeypatch: Per-test patch manager.
        tmp_path: Temporary artifact directory.
    """
    name = "album" if mutation == "ceil-threshold" else "requeue"
    dry_run = mutation == "write-in-dry-run"
    trace = Trace(tmp_path)
    scenario = FACTORIES[name](monkeypatch, tmp_path, trace)
    _install_regression(monkeypatch, mutation)
    capture(trace, scenario, tmp_path, dry_run)
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / f"{name}-{'dry' if dry_run else 'normal'}.json"
    )
    expected = json.loads(fixture.read_text())
    assert any(
        event["operation"] == "run" and event["phase"] == "result"
        for event in trace.events
    )
    with pytest.raises(AssertionError):
        assert trace.events == expected
