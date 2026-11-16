"""Hand-calculated temporal, identity, discovery, and concentration contracts."""

from datetime import date

import pytest

from spotify_manager.domain.listening_activity import listening_activity
from spotify_manager.domain.listening_activity import summarize_listening
from spotify_manager.domain.listening_evolution import listening_evolution
from spotify_manager.domain.listening_insights import compare_listening
from spotify_manager.domain.listening_insights import forgotten_favorites
from spotify_manager.domain.listening_insights import listening_discoveries
from spotify_manager.domain.listening_time import bucket_name
from spotify_manager.domain.listening_time import bucket_names
from spotify_manager.domain.listening_time import hour_occurrences
from spotify_manager.domain.listening_time import listening_bounds
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_time import selected_rhythm
from spotify_manager.domain.listening_time import utc_iso
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import ListeningCounts
from spotify_manager.domain.listening_values import ListeningQuery
from tests.support.listening import timestamp


def play(day: str, artist: str = "alpha") -> ArtistPlay:
    return ArtistPlay(timestamp(day), artist, artist.title(), "track-" + artist)


def test_identity_preserves_accents_punctuation_and_component_boundaries() -> None:
    assert listening_identity(("  BÉTA ",)) == listening_identity(("be\u0301ta",))
    assert listening_identity(("Béta",)) != listening_identity(("Beta",))
    assert listening_identity(("A-B",)) != listening_identity(("AB",))
    assert listening_identity(("a", "bc")) != listening_identity(("ab", "c"))


@pytest.mark.parametrize(
    "day,hours", [(date(2024, 3, 31), 23), (date(2024, 10, 27), 25)]
)
def test_dst_days_and_rhythm_use_actual_utc_occurrences(day: date, hours: int) -> None:
    query = ListeningQuery(day, day)
    start, end = listening_bounds(query)
    assert (end - start) / 3600000 == hours
    counts = hour_occurrences(query, (start, end - 1))
    assert sum(counts.values()) == pytest.approx(hours)
    if hours == 23:
        assert counts.get((6, 2), 0) == 0
    else:
        assert counts[(6, 2)] == pytest.approx(2)


def test_partial_hours_empty_coverage_and_rhythm_selection() -> None:
    query = ListeningQuery(
        date(2024, 1, 1), date(2024, 1, 1), "UTC", weekday=0, hour=12
    )
    first, last = timestamp("2024-01-01T12:30:00"), timestamp("2024-01-01T12:45:00")
    assert hour_occurrences(query, (first, last))[(0, 12)] == pytest.approx(
        0.25, abs=0.000001
    )
    assert hour_occurrences(query, (None, None)) == {}
    assert not selected_rhythm(
        local_instant(first, "UTC"),
        ListeningQuery(query.start, query.end, "UTC", weekday=1),
    )
    assert not selected_rhythm(
        local_instant(first, "UTC"),
        ListeningQuery(query.start, query.end, "UTC", hour=11),
    )
    assert selected_rhythm(local_instant(first, "UTC"), query)
    assert utc_iso(None) is None
    assert utc_iso(first) == "2024-01-01T12:30:00+00:00"


def test_calendar_counts_duplicates_and_distinguishes_unobserved_dates() -> None:
    first, last = timestamp("2024-02-28T23:30:00"), timestamp("2024-03-01T12:00:00")
    query = ListeningQuery(date(2024, 2, 28), date(2024, 3, 2))
    result = listening_activity((first, first, last), query, (first, last))
    assert [item.plays for item in result.days] == [0, 2, 1, 0]
    assert [item.covered for item in result.days] == [False, True, True, False]
    assert [item.partial for item in result.days] == [False, True, True, False]
    assert sum(item.plays for item in result.hours) == 3
    assert len(result.hours) == 168
    empty = listening_activity((), query, (None, None))
    assert not any(item.covered for item in empty.days)
    assert all(item.average == 0 for item in empty.hours)


def test_overview_averages_use_explicit_separate_denominators() -> None:
    query = ListeningQuery(date(2024, 1, 1), date(2024, 1, 4))
    counts = ListeningCounts(10, 2, 3, 1, 2, 1, 1, 2)
    overview = summarize_listening(counts, query)
    assert overview.per_calendar_day == 2.5
    assert overview.per_active_day == 5
    empty = summarize_listening(ListeningCounts(0, 0, 0, 0, 0, 0, None, None), query)
    assert empty.per_active_day == 0


def test_evolution_has_fixed_eight_plus_other_and_empty_buckets() -> None:
    plays = []
    for index in range(10):
        plays.append(play("2024-01-03T12:00:00", str(index)))
    plays.append(play("2024-03-03T12:00:00", "0"))
    query = ListeningQuery(date(2024, 1, 1), date(2024, 3, 31), "UTC")
    result = listening_evolution(tuple(plays), query, "month")
    assert result.buckets == ("2024-01", "2024-02", "2024-03")
    assert len(result.series) == 9
    assert result.series[-1].key == "other"
    assert result.series[-1].counts == (2, 0, 0)
    assert sum(item.counts[0] for item in result.series) == 10
    assert result.breadth[0].artists == 10
    assert result.breadth[0].tracks == 10
    assert result.breadth[1].top_artist_share == 0
    assert result.breadth[2].top_artist_share == 1
    assert bucket_name(date(2024, 1, 3), "week") == "2024-01-01"
    assert bucket_names(query, "week")[0] == "2024-01-01"
    assert listening_evolution((), query, "month").series[0].counts == (0, 0, 0)


def test_discovery_never_resets_firsts_and_excludes_incomplete_windows() -> None:
    plays = (
        play("2023-12-01T12:00:00", "old"),
        play("2024-01-01T12:00:00", "old"),
        play("2024-01-01T12:00:00"),
        play("2024-01-01T15:00:00"),
        play("2024-01-08T12:00:00"),
        play("2024-01-20T12:00:00", "new"),
    )
    query = ListeningQuery(date(2024, 1, 1), date(2024, 1, 31), "UTC")
    result = listening_discoveries(plays, query, timestamp("2024-02-01T12:00:00"))
    cohort = result.cohorts[0]
    assert cohort.artists == 2
    assert cohort.eligible_7 == 2 and cohort.returned_7 == 1
    assert cohort.eligible_30 == 1 and cohort.returned_30 == 1
    assert cohort.eligible_90 == 0
    assert result.observed_through == date(2024, 1, 31)
    assert listening_discoveries((), query, None).observed_through is None
    empty = listening_discoveries(
        (play("2024-01-01T12:00:00"), play("2024-01-01T13:00:00")),
        query,
        timestamp("2024-04-02T12:00:00"),
    )
    assert empty.cohorts[0].returned_7 == 0


def test_forgotten_favorites_thresholds_and_stable_ties() -> None:
    query = ListeningQuery(date(2024, 3, 1), date(2024, 3, 10), "UTC")
    old = timestamp("2024-01-01T12:00:00")
    recent = timestamp("2024-03-09T12:00:00")
    history = (
        EntityLifetime("b", "B", "B", 50, old, old),
        EntityLifetime("a", "A", "A", 50, old, old),
        EntityLifetime("r", "R", "R", 60, old, recent),
        EntityLifetime("s", "S", "S", 49, old, old),
    )
    result = forgotten_favorites(history, query, (50, 30))
    assert [item.entity.key for item in result.items] == ["a", "b"]
    assert result.items[0].days_since_last == 69
    assert result.total == 2 and result.as_of == query.end


def test_comparison_handles_zero_periods_and_pre_source_coverage() -> None:
    query = ListeningQuery(date(2024, 2, 1), date(2024, 2, 29), "UTC")
    observed = timestamp("2024-01-01T12:00:00")
    old = (EntityLifetime("a", "A", "A", 2, observed, observed),)
    current = (EntityLifetime("b", "B", "B", 4, observed, observed),)
    result = compare_listening((old, current), query, observed)
    assert result.previous_start == date(2024, 1, 3)
    assert result.previous_end == date(2024, 1, 31)
    assert result.previous_covered
    assert result.items[0].key == "b" and result.items[0].current_share == 1
    assert result.items[1].previous_share == 1
    empty = compare_listening(((), current), query, None)
    assert not empty.previous_covered and empty.items[0].previous_share == 0
    inverse = compare_listening((old, ()), query, None)
    assert inverse.items[0].current_share == 0
