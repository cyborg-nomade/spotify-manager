"""Protect original tolerant stored-plan execution and malformed-source guards."""

from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.application.queue_flush import QueueFlush
from spotify_manager.application.queue_values import QueueStateError
from tests.support.queue_fill import TRACK
from tests.support.queue_flush import SOURCE
from tests.support.queue_flush import FlushObservations
from tests.support.queue_flush_application import MemoryQueueFlush


def _resume(plan: dict[str, object]) -> FlushObservations:
    observations = FlushObservations("resume-plan")
    observations.state["active_flush"] = {
        "run_id": "stored",
        "playlist_id": "queue",
        "entries": [{"source": asdict(SOURCE), "status": "pending", "plan": plan}],
    }
    return observations


def test_original_malformed_source_uris_fail_before_destination_effects() -> None:
    """Reject source URI shape after decoding the stored target and before writes."""
    plan: dict[str, object] = {
        "action": "advance",
        "target": asdict(TRACK),
        "source_uris": None,
    }
    observations = _resume(plan)
    with pytest.raises(QueueStateError, match="invalid source URIs"):
        QueueFlush(MemoryQueueFlush(observations)).run(False)
    assert not any(
        row[0] in {"append", "remove", "audit"} for row in observations.trace
    )
    assert not observations.checkpoints


def test_original_unknown_action_with_target_still_removes_source() -> None:
    """Retain legacy unknown-action tolerance instead of adding stricter validation."""
    observations = FlushObservations("unknown")
    plan = observations.plan_record([SOURCE.uri])
    plan["target"] = asdict(TRACK)
    observations = _resume(plan)
    result = QueueFlush(MemoryQueueFlush(observations)).run(False)
    assert cast(str, result.results[0].action) == "unknown"
    assert result.playlist_length_after == 0
    assert not any(row[0] == "append" for row in observations.trace)
    assert any(row[0] == "remove" for row in observations.trace)
