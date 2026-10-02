"""Protect Queue promotion thresholds, marker cursors and rejection reasons."""

import json
from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.domain.queue_flush_decision import QueuePlan
from spotify_manager.domain.queue_flush_decision import choose_queue_action
from spotify_manager.domain.queue_flush_decision import first_primary_marker
from spotify_manager.domain.queue_flush_decision import resolved_promotion
from tests.support.queue_fill import TRACK
from tests.support.queue_flush import SOURCE
from tests.support.queue_planning import cases
from tests.support.queue_planning import observations


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_queue_decisions_match_original(name: str, case: dict[str, object]) -> None:
    """Retain original decisions from already observed facts without catalog calls.

    Args:
        name: Original immutable fact scenario identifier.
        case: Original threshold, cursor and marker facts.
    """
    assert name
    edge = observations(case)
    tracks = edge.tracks()
    liked: dict[str, bool] = {}
    for index, track in enumerate(tracks):
        liked[track.spotify_id] = index < edge.liked_top
    decision = choose_queue_action(
        SOURCE.spotify_id,
        tracks,
        liked,
        edge.liked_total,
        TRACK if edge.liked_total else None,
    )
    release = None
    if decision.action == "promote":
        target = first_primary_marker(edge.promotion_tracks(), "artist")
        decision = resolved_promotion(decision.reason, target)
        release = "Release" if target is not None else None
    plan = QueuePlan(
        decision.action,
        [SOURCE.uri],
        decision.target,
        release,
        len(tracks),
        sum(liked.values()),
        edge.liked_total,
        decision.reason,
    )
    expected = cast(dict[str, object], case["outcome"])
    assert json.loads(json.dumps(asdict(plan))) == expected["plan"]


def test_empty_top_window_and_promotion_catalog() -> None:
    """Preserve empty top-track rejection and absent primary marker behavior."""
    assert choose_queue_action("source", (), {}, 0, None).action == "unfollow"
    assert first_primary_marker((), "artist") is None
