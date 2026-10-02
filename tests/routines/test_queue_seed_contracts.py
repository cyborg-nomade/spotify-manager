"""Protect original Queue history aggregation and deterministic weekly seed choice."""

from dataclasses import asdict
from datetime import date
from typing import cast

import pytest

from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import the_queue as legacy
from tests.support.queue_policy import PolicyCase
from tests.support.queue_policy import cases
from tests.support.queue_policy import records


def _history(case: PolicyCase) -> dict[str, object]:
    plays: list[Scrobble] = []
    for row in records(case):
        plays.append(
            Scrobble(
                cast(str, row["track"]),
                cast(str, row["artist"]),
                cast(str, row["album"]),
                cast(int, row["timestamp_ms"]),
            )
        )
    return {
        "result": [asdict(artist) for artist in legacy.aggregate_artist_history(plays)]
    }


def _artists(case: PolicyCase) -> tuple[legacy.ArtistHistory, ...]:
    artists: list[legacy.ArtistHistory] = []
    for row in records(case):
        artists.append(
            legacy.ArtistHistory(
                cast(str, row["artist"]),
                cast(str, row["key"]),
                cast(int, row["play_count"]),
                cast(int, row["recent_play_count"]),
                cast(int, row["annual_play_count"]),
                cast(int, row["last_played_ms"]),
            )
        )
    return tuple(artists)


def _seeds(case: PolicyCase) -> dict[str, object]:
    try:
        seeds = legacy.select_seed_artists(
            _artists(case),
            seed_count=cast(int, case["count"]),
            week_start=date.fromisoformat(cast(str, case["week"])),
        )
        return {"result": [asdict(seed) for seed in seeds]}
    except (legacy.QueueConfigError, legacy.QueueStateError) as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_queue_original_history_and_seed_contracts(name: str, case: PolicyCase) -> None:
    """Preserve cutoff anchors, display ties, quota/fallback order and weekly rotation.

    Args:
        name: Original immutable scenario identity.
        case: Original input fields and expected outcome.
    """
    expected = case["outcome"]
    if name.startswith("history:"):
        assert _history(case) == {"result": expected}
        return
    assert _seeds(case) == expected
