"""Verify pure Queue aggregation and seed selection against immutable originals."""

from dataclasses import asdict
from datetime import date
from typing import cast

import pytest

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.queue_history import aggregate_artists
from spotify_manager.domain.queue_seeds import select_seeds
from spotify_manager.domain.queue_values import ArtistHistory
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
    return {"result": [asdict(artist) for artist in aggregate_artists(plays)]}


def _artists(case: PolicyCase) -> tuple[ArtistHistory, ...]:
    artists: list[ArtistHistory] = []
    for row in records(case):
        artists.append(
            ArtistHistory(
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
    seeds = select_seeds(
        _artists(case),
        cast(int, case["count"]),
        date.fromisoformat(cast(str, case["week"])),
    )
    return {"result": [asdict(seed) for seed in seeds]}


def _domain_cases() -> list[tuple[str, PolicyCase]]:
    selected: list[tuple[str, PolicyCase]] = []
    for name, case in cases():
        if name.startswith("history:"):
            selected.append((name, case))
            continue
        outcome = cast(dict[str, object], case["outcome"])
        if "result" in outcome:
            selected.append((name, case))
    return selected


DOMAIN_CASES = _domain_cases()


@pytest.mark.parametrize(
    "name,case", DOMAIN_CASES, ids=[name for name, _case in DOMAIN_CASES]
)
def test_pure_queue_history_and_seed_originals(name: str, case: PolicyCase) -> None:
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
