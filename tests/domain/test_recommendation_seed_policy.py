"""Weekly quota, diversity and fallback seed policies over original fixtures."""

from datetime import date
from typing import cast

import pytest

from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_seeds import choose_seeds
from tests.support.recommendation_seeds import seed_cases
from tests.support.recommendation_seeds import seed_history
from tests.support.recommendation_seeds import seed_records


WEEK = date(2026, 7, 17)


@pytest.mark.parametrize("case", seed_cases())
def test_seed_policy_matches_original_exact_decisions(case: dict[str, object]) -> None:
    """Preserve quotas, source fields, scores, ordering and duplicate-input tolerance.

    Args:
        case: Original pre-extraction listening statistics and seed decisions.
    """
    selected = choose_seeds(
        tuple(seed_history(case)),
        cast(int, case["seed_count"]),
        date.fromisoformat(str(case["week_start"])),
    )
    if "error" in case:
        assert len(selected) == 2
        return
    assert seed_records(selected) == case["seeds"]


def test_limits_remain_configurable_and_fallback_keeps_artist_cap() -> None:
    """Respect the original supplied per-artist cap through all selection stages."""
    tracks = tuple(seed_history(seed_cases()[0]))
    assert len(choose_seeds(tracks, 6, WEEK, max_per_artist=0)) == 0
    assert len(choose_seeds(tracks, 6, WEEK, pool_multiplier=0)) == 6
    same_artist = tuple(seed_history(seed_cases()[-1]))
    assert len(choose_seeds(same_artist, 4, WEEK, max_per_artist=3)) == 3


def test_zero_play_fallback_retains_zero_weight_rank_and_seed_weight() -> None:
    """Fallback considers zero-play histories after grouped positive pools are empty."""
    track = TrackHistory("Artist", "Song", ("artist", "song"), 0, 0, 0, 0)
    seeds = choose_seeds((track,), 1, WEEK)
    assert len(seeds) == 1
    assert seeds[0].source == "overall" and seeds[0].source_play_count == 0
    assert seeds[0].weight == 1.0 and seeds[0].weekly_rank == 0.0


def test_selection_keeps_duplicate_history_keys_within_one_group() -> None:
    """Preserve the original group-pool behavior for manually duplicated inputs."""
    track = TrackHistory("Artist", "Song", ("artist", "song"), 1, 1, 1, 1)
    selected = choose_seeds((track, track), 6, WEEK)
    assert len(selected) == 2
    assert selected[0] == selected[1] and selected[0].source == "recent"


def test_negative_play_count_keeps_original_math_error() -> None:
    """A negative fallback count still raises before accepting any seed."""
    track = TrackHistory("Artist", "Song", ("artist", "song"), -1, 0, 0, 0)
    with pytest.raises(ValueError):
        choose_seeds((track,), 1, WEEK)
