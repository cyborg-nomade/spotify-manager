"""Retain original history, calendar, random and seconds selection traces."""

import json
from dataclasses import asdict
from datetime import date
from functools import partial
from typing import cast

import pytest

from spotify_manager.application.discography_history import DiscographyHistory
from spotify_manager.application.discography_history import resolve_historical
from spotify_manager.application.discography_values import DiscographyCancelledError
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from tests.support.discography_boundaries import history_outcome
from tests.support.discography_run import FIXTURE
from tests.support.discography_run import cases
from tests.support.discography_run import historical
from tests.support.palace_history import HistoryReads


def _cutoff() -> date:
    return date(2025, 12, 31)


def _outcome(profile: str, second: int) -> object:
    edge = HistoryReads(profile, second)
    owner = DiscographyHistory(
        partial(edge.read, FIXTURE.with_name("history")),
        _cutoff,
        edge.random,
        edge.progress,
        date(2007, 11, 27),
    )
    result: dict[str, object] = {}
    try:
        result["result"] = asdict(owner.run())
    except (RuntimeError, IndexError) as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


@pytest.mark.parametrize("case", cases("discography_history.json"))
def test_discography_history_matches_original_complete_observations(
    case: dict[str, object],
) -> None:
    """Compare complete selections and original malformed-reader error prefixes.

    Args:
        case: Original immutable history and random input.
    """
    profile, second = cast(str, case["profile"]), cast(int, case["second"])
    assert _outcome(profile, second) == case["outcome"]
    assert history_outcome(profile, second) == case["outcome"]


def _mapping(profile: str, name: str) -> SpotifyArtistCandidate | None:
    assert name == "Past"
    if profile == "error":
        raise SomethingOldError("mapping failed")
    if profile == "cancel":
        return None
    return SpotifyArtistCandidate("past", "Past", "uri", 9, 4, 2)


@pytest.mark.parametrize("profile", ["normal", "error", "cancel"])
def test_discography_mapping_keeps_original_translation_and_cancellation(
    profile: str,
) -> None:
    """Retain exact mapped facts and original error identity/message.

    Args:
        profile: Original successful, failed or cancelled mapping.
    """
    callback = partial(_mapping, profile)
    if profile == "normal":
        candidate = resolve_historical(historical(), callback)
        assert (candidate.spotify_id, candidate.name, candidate.queue) == (
            "past",
            "Past",
            "memory_lane",
        )
        return
    error = DiscographyCancelledError if profile == "cancel" else DiscographyError
    with pytest.raises(error):
        resolve_historical(historical(), callback)
