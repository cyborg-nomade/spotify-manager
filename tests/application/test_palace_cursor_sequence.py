"""Protect original manual cursor live refresh, validation and checkpoint order."""

import json
from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.application.palace_cursor import PalaceCursor
from tests.application.test_palace_workflow import MemoryPalace
from tests.support.palace_run import FIXTURE
from tests.support.palace_run import PalaceObservations
from tests.support.palace_run import cursor_outcome


def _cases() -> list[dict[str, object]]:
    return cast(
        list[dict[str, object]],
        json.loads(FIXTURE.with_name("palace_cursor_run.json").read_text()),
    )


def _outcome(position: int, failure: str | None) -> object:
    edge = PalaceObservations("normal", failure)
    effects = MemoryPalace(edge)
    result: dict[str, object] = {}
    try:
        update = PalaceCursor(
            effects.progress,
            effects.refresh,
            effects.state_access,
            effects.cursor_payload,
        ).update(position)
        result["result"] = {
            "next_index": update.next_index,
            "next_album": update.next_album.model_dump(),
            "album_refresh": asdict(update.album_refresh),
        }
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


@pytest.mark.parametrize("case", _cases())
def test_palace_cursor_matches_original_manual_update(case: dict[str, object]) -> None:
    """Retain refresh-before-validation and load-before-checkpoint behavior.

    Args:
        case: Immutable original requested position and effect evidence.
    """
    position = cast(int, case["position"])
    failure = cast(str | None, case["failure"])
    assert cursor_outcome(position, failure) == case["outcome"]
    assert _outcome(position, failure) == case["outcome"]
