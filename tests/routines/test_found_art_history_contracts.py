"""Original history aggregation and week-ranking contracts before extraction."""

from collections.abc import Iterator
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta

from spotify_manager.routines import blast_from_past
from spotify_manager.routines import found_art


DAY_MS = 86400000


def _plays() -> Iterator[blast_from_past.Scrobble]:
    yield blast_from_past.Scrobble("First - Remastered", "Ártist", "", 0)
    yield blast_from_past.Scrobble("First", "ARTIST", "", 310 * DAY_MS)
    yield blast_from_past.Scrobble("FIRST", "Artist", "", 310 * DAY_MS)
    yield blast_from_past.Scrobble("Second", "Other", "", 400 * DAY_MS)
    yield blast_from_past.Scrobble("Old", "Earlier", "", 35 * DAY_MS)


def test_aggregation_preserves_first_seen_order_and_strict_display_timestamp() -> None:
    """Preserve inclusive annual/recent bounds and first display spelling on ties."""
    result = found_art.aggregate_track_history(_plays())
    assert [track.key for track in result] == [
        ("artist", "first"),
        ("other", "second"),
        ("earlier", "old"),
    ]
    first = result[0]
    assert (first.artist, first.track, first.last_played_ms) == (
        "ARTIST",
        "First",
        310 * DAY_MS,
    )
    assert (first.play_count, first.recent_play_count, first.annual_play_count) == (
        3,
        2,
        2,
    )
    assert (result[2].recent_play_count, result[2].annual_play_count) == (0, 1)


def test_invalid_latest_play_still_sets_recency_anchor() -> None:
    """Retain the existing cutoff anchor even when that play has an empty identity."""
    plays = [
        blast_from_past.Scrobble("Song", "Artist", "", 1),
        blast_from_past.Scrobble("!!!", "Artist", "", 1000 * DAY_MS),
    ]
    result = found_art.aggregate_track_history(plays)
    assert len(result) == 1
    assert result[0].play_count == 1
    assert result[0].recent_play_count == result[0].annual_play_count == 0
    assert found_art.aggregate_track_history([plays[1]]) == ()


def test_listening_week_uses_berlin_friday_after_timezone_conversion() -> None:
    """Interpret naive times as UTC and convert aware times to Berlin."""
    utc_thursday = datetime(2026, 7, 16, 22, 30, tzinfo=UTC)
    assert found_art.listening_week_start(utc_thursday) == date(2026, 7, 17)
    assert found_art.listening_week_start(utc_thursday.replace(tzinfo=None)) == date(
        2026, 7, 17
    )
    assert found_art.listening_week_start(date(2026, 7, 16)) == date(2026, 7, 10)
    assert found_art.listening_week_start(utc_thursday - timedelta(hours=1)) == date(
        2026, 7, 10
    )


def test_weekly_rank_preserves_hash_namespace_and_weight_floor() -> None:
    """Preserve exact original ranks, namespaces and the sampling weight floor."""
    week, key = date(2026, 7, 17), ("artist", "song")
    rank = found_art.weekly_weighted_rank(week, "seed:recent", key, 1.0)
    assert rank == 0.43765392284774446
    assert found_art.weekly_weighted_rank(week, "seed:recent", key, -1.0) == 0.0
    assert found_art.weekly_weighted_rank(week, "seed:recent", key, 0.0) == 0.0
    assert found_art.weekly_weighted_rank(week, "seed:recent", key, 0.5) == rank**2
    assert found_art.weekly_weighted_rank(week, "other", key, 1.0) != rank
