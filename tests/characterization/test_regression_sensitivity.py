"""Prove the golden fixtures reject representative unsafe refactors."""

import json
import math
from pathlib import Path

import pytest

from spotify_manager.processors import library_lookups
from spotify_manager.routines import requeue_for_a_dream
from tests.characterization.scenarios import FACTORIES
from tests.characterization.test_routine_traces import capture
from tests.support.effects import Trace


@pytest.mark.parametrize(
    "mutation", ["ceil-threshold", "remove-first", "missing-audit", "write-in-dry-run"]
)
def test_golden_contract_rejects_deliberate_regression(mutation, monkeypatch, tmp_path):
    name = "album" if mutation == "ceil-threshold" else "requeue"
    dry_run = mutation == "write-in-dry-run"
    trace = Trace(tmp_path)
    scenario = FACTORIES[name](monkeypatch, tmp_path, trace)
    if mutation == "ceil-threshold":
        monkeypatch.setattr(library_lookups, "floor", math.ceil)
    elif mutation == "remove-first":
        original = requeue_for_a_dream._add_track

        def remove_first(spotify, playlist_id, track, retry):
            spotify._delete(
                f"playlists/{playlist_id}/items",
                payload={"items": [{"uri": "spotify:track:t1"}]},
            )
            original(spotify, playlist_id, track, retry)

        monkeypatch.setattr(requeue_for_a_dream, "_add_track", remove_first)
    elif mutation == "missing-audit":
        monkeypatch.setattr(requeue_for_a_dream, "_append_log", lambda *args: None)
    else:
        original = requeue_for_a_dream.flush_requeue_for_a_dream

        def ignore_dry_run(*args, **kwargs):
            kwargs["dry_run"] = False
            return original(*args, **kwargs)

        monkeypatch.setattr(
            requeue_for_a_dream, "flush_requeue_for_a_dream", ignore_dry_run
        )
    capture(trace, scenario, tmp_path, dry_run)
    expected = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / f"{name}-{'dry' if dry_run else 'normal'}.json"
        ).read_text()
    )
    assert any(
        event["operation"] == "run" and event["phase"] == "result"
        for event in trace.events
    )
    # An intentionally changed implementation must fail the normal parity assertion.
    with pytest.raises(AssertionError):
        assert trace.events == expected
