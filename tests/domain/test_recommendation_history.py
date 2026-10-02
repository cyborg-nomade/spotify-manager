"""Pure recommendation history identity, statistics and weekly ranking contracts."""

from collections.abc import Iterator
from datetime import date
from datetime import timedelta

import pytest

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.recommendation_history import DAY_MS
from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_history import aggregate_track_history
from spotify_manager.domain.recommendation_history import canonical_track_key
from spotify_manager.domain.recommendation_history import listening_week_start
from spotify_manager.domain.recommendation_history import weekly_unit_interval
from spotify_manager.domain.recommendation_history import weekly_weighted_rank


def _plays() -> Iterator[Scrobble]:
    yield Scrobble("Song - Remastered", "Ártist", "", 0)
    yield Scrobble("Song", "ARTIST", "", 310 * DAY_MS)
    yield Scrobble("SONG", "Artist", "", 310 * DAY_MS)
    yield Scrobble("Other", "Second", "", 400 * DAY_MS)
    yield Scrobble("Old", "Third", "", 35 * DAY_MS)


def test_aggregation_retains_order_bounds_and_first_spelling_on_ties() -> None:
    """Keep inclusive 90/365-day counts and replace display only for newer plays."""
    assert aggregate_track_history(_plays()) == (
        TrackHistory("ARTIST", "Song", ("artist", "song"), 3, 2, 2, 310 * DAY_MS),
        TrackHistory("Second", "Other", ("second", "other"), 1, 1, 1, 400 * DAY_MS),
        TrackHistory("Third", "Old", ("third", "old"), 1, 0, 1, 35 * DAY_MS),
    )


def test_invalid_newest_play_still_anchors_recency_windows() -> None:
    """Set the cutoff before filtering invalid artist/title identities."""
    invalid = Scrobble("!!!", "Artist", "", 1000 * DAY_MS)
    result = aggregate_track_history([Scrobble("Song", "Artist", "", 1), invalid])
    assert result == (TrackHistory("Artist", "Song", ("artist", "song"), 1, 0, 0, 1),)
    assert aggregate_track_history([invalid]) == ()
    assert aggregate_track_history([]) == ()


def test_older_later_encounter_does_not_replace_display() -> None:
    """Keep the newest valid spelling even if an older normalized play appears later."""
    plays = [
        Scrobble("Newest", "Ártist", "", 2000),
        Scrobble("NEWEST", "ARTIST", "", 1000),
    ]
    result = aggregate_track_history(plays)
    assert result[0].artist == "Ártist" and result[0].track == "Newest"
    assert (
        result[0].play_count
        == result[0].recent_play_count
        == result[0].annual_play_count
        == 2
    )


@pytest.mark.parametrize(
    "artist,track,key",
    [
        ("Beyoncé", "Song - Remastered", ("beyonce", "song")),
        ("Artist", "Song (Live)", ("artist", "song")),
        ("!!!", "Song", ("", "song")),
        ("Artist", "!!!", ("artist", "")),
    ],
)
def test_canonical_keys_preserve_edition_and_live_title_rules(
    artist: str, track: str, key: tuple[str, str]
) -> None:
    """Only recognized sliding qualifiers collapse into the base track identity.

    Args:
        artist: Original display artist.
        track: Original display title.
        key: Expected normalized identity.
    """
    assert canonical_track_key(artist, track) == key


@pytest.mark.parametrize("days", range(7))
def test_week_start_keeps_friday_for_all_days_in_the_week(days: int) -> None:
    """Each already-resolved local date maps to the same Friday.

    Args:
        days: Days after Friday within the listening week.
    """
    friday = date(2026, 7, 17)
    assert listening_week_start(friday + timedelta(days=days)) == friday


@pytest.mark.parametrize(
    "weight,expected",
    [
        (-1.0, 0.0),
        (0.0, 0.0),
        (0.5, 0.19154095618401945),
        (1.0, 0.43765392284774446),
        (10.0, 0.9206892716495315),
    ],
)
def test_weekly_rank_keeps_original_hash_and_weight_floor(
    weight: float, expected: float
) -> None:
    """Compare exact results captured before extraction, including underflow to zero.

    Args:
        weight: Original sampling weight.
        expected: Exact original rank.
    """
    assert (
        weekly_weighted_rank(
            date(2026, 7, 17), "seed:recent", ("artist", "song"), weight
        )
        == expected
    )


def test_hash_keeps_week_namespace_and_both_identity_parts() -> None:
    """Retain every original component in the deterministic ranking identity."""
    week, key = date(2026, 7, 17), ("artist", "song")
    fraction = weekly_unit_interval(week, "seed:recent", key)
    assert fraction == 0.43765392284774446
    assert weekly_unit_interval(date(2026, 7, 24), "seed:recent", key) != fraction
    assert weekly_unit_interval(week, "other", key) != fraction
    assert weekly_unit_interval(week, "seed:recent", ("other", "song")) != fraction
    assert weekly_unit_interval(week, "seed:recent", ("artist", "other")) != fraction
