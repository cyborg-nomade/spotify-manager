"""Verify original restart recovery after accepted writes and checkpoint failures."""

import json
from dataclasses import asdict

import pytest

from spotify_manager.application.queue_flush import QueueFlush
from tests.support.queue_flush import restart_cases
from tests.support.queue_flush import restart_observations
from tests.support.queue_flush_application import MemoryQueueFlush


@pytest.mark.parametrize(
    "name,case", restart_cases(), ids=[name for name, _case in restart_cases()]
)
def test_queue_restart_matches_original(name: str, case: dict[str, object]) -> None:
    """Re-read accepted state and live membership before replaying stored plans.

    Args:
        name: Original interruption scenario identifier.
        case: Original failed-run and recovery observations.
    """
    assert name
    edge = restart_observations(case)
    outcome: dict[str, object] = {
        "result": asdict(QueueFlush(MemoryQueueFlush(edge)).run(False))
    }
    outcome.update(trace=edge.trace, state=edge.state, checkpoints=edge.checkpoints)
    playlists: dict[str, list[str]] = {}
    for playlist, tracks in edge.playlists.items():
        playlists[playlist] = [track.spotify_id for track in tracks]
    outcome["playlists"] = playlists
    assert json.loads(json.dumps(outcome, default=str)) == case["restart_outcome"]
