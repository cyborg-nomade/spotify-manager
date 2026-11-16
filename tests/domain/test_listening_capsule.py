"""Hand-calculated period similarity and exact local calendar anniversaries."""

from datetime import date

import pytest

from spotify_manager.domain.listening_capsule import listening_anniversaries
from spotify_manager.domain.listening_capsule import listening_eras
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import ListeningQuery
from tests.support.listening import timestamp


def play(when: str, artist: str = "alpha") -> ArtistPlay:
    return ArtistPlay(timestamp(when), artist, artist.title(), "track-" + artist)


def test_eras_uses_all_artist_shares_and_keeps_empty_comparisons_undefined() -> None:
    plays = (
        play("2024-01-01T12:00:00"),
        play("2024-01-02T12:00:00"),
        play("2024-01-03T12:00:00", "beta"),
        play("2024-03-01T12:00:00"),
        play("2024-03-02T12:00:00", "beta"),
        play("2024-03-03T12:00:00", "beta"),
        play("2024-04-01T12:00:00", "gamma"),
    )
    query = ListeningQuery(date(2024, 1, 1), date(2024, 4, 30), "UTC")
    result = listening_eras(
        plays, query, (plays[0].timestamp_ms, plays[-1].timestamp_ms)
    )
    assert result.grain == "month"
    assert [item.plays for item in result.periods] == [3, 0, 3, 1]
    assert result.similarities[0] == (1.0, None, 0.5, 0.0)
    assert result.similarities[1] == (None, None, None, None)
    assert result.similarities[2][0] == 0.5
    assert result.similarities[3][3] == 1
    assert result.periods[0].partial and result.periods[3].partial
    assert result.periods[1].covered and not result.periods[1].partial


def test_eras_volume_invariance_and_artists_beyond_the_top_eight() -> None:
    january = []
    february = []
    for index in range(12):
        january.append(play("2024-01-10T12:00:00", str(index)))
        february.extend([play("2024-02-10T12:00:00", str(index))] * 3)
    query = ListeningQuery(date(2024, 1, 1), date(2024, 2, 29), "UTC")
    result = listening_eras(tuple(january + february), query, (None, None))
    assert result.similarities == ((1.0, 1.0), (1.0, 1.0))
    assert result.periods[0].artists == 12
    assert not result.periods[0].covered


def test_eras_timezone_clipping_and_source_coverage() -> None:
    instant = play("2024-01-31T23:30:00")
    query = ListeningQuery(date(2024, 1, 15), date(2024, 3, 10))
    result = listening_eras(
        (instant,), query, (instant.timestamp_ms, instant.timestamp_ms)
    )
    assert [item.plays for item in result.periods] == [0, 1, 0]
    assert result.periods[0].start == date(2024, 1, 15)
    assert result.periods[2].end == date(2024, 3, 10)
    assert not result.periods[0].covered and not result.periods[2].covered
    assert result.periods[1].covered and result.periods[1].partial
    assert result.similarities[2][1] is None


@pytest.mark.parametrize(
    "end,grain,size",
    [(date(2019, 12, 31), "month", 240), (date(2020, 1, 1), "year", 21)],
)
def test_eras_matrix_bound_switches_to_explicit_calendar_years(
    end: date, grain: str, size: int
) -> None:
    query = ListeningQuery(date(2000, 1, 1), end, "UTC")
    observation = play("2010-01-01T12:00:00")
    result = listening_eras(
        (observation,), query, (observation.timestamp_ms, observation.timestamp_ms)
    )
    assert result.grain == grain and len(result.periods) == size
    assert result.periods[-1].end == end
    assert sum(item.plays for item in result.periods) == 1
    assert len(result.similarities) == size


def test_eras_selection_boundaries_remain_partial_inside_complete_coverage() -> None:
    query = ListeningQuery(date(2024, 2, 10), date(2024, 2, 20), "UTC")
    coverage = timestamp("2023-01-01T12:00:00"), timestamp("2025-01-01T12:00:00")
    period = listening_eras((), query, coverage).periods[0]
    assert period.covered and period.partial
    assert period.start == query.start and period.end == query.end


def test_anniversaries_ignore_start_keep_zero_years_and_exclude_current_year() -> None:
    plays = (
        play("2021-06-05T12:00:00"),
        play("2021-06-05T12:00:00"),
        play("2021-06-05T13:00:00", "beta"),
        play("2022-06-06T12:00:00"),
        play("2023-06-05T12:00:00", "gamma"),
        play("2024-06-05T12:00:00", "future"),
    )
    query = ListeningQuery(date(2023, 6, 1), date(2023, 6, 5), "UTC")
    result = listening_anniversaries(
        plays, query, (plays[0].timestamp_ms, plays[-1].timestamp_ms)
    )
    assert result.as_of == query.end
    assert [item.day for item in result.days] == [date(2021, 6, 5), date(2022, 6, 5)]
    assert [item.plays for item in result.days] == [3, 0]
    assert result.days[0].artists == 2
    assert result.days[0].top_artists[0].share == pytest.approx(2 / 3)
    assert result.days[0].partial and result.days[1].covered
    assert not result.days[1].partial and result.days[1].top_artists == ()


def test_anniversaries_preserve_leap_day_and_convert_timezone_before_matching() -> None:
    plays = (play("2016-02-28T23:30:00"), play("2020-02-29T12:00:00"))
    query = ListeningQuery(date(2024, 2, 1), date(2024, 2, 29))
    result = listening_anniversaries(
        plays, query, (plays[0].timestamp_ms, plays[-1].timestamp_ms)
    )
    assert [item.day for item in result.days] == [date(2016, 2, 29), date(2020, 2, 29)]
    assert [item.plays for item in result.days] == [1, 1]
    assert all(item.partial for item in result.days)


def test_anniversaries_distinguish_outside_coverage_and_empty_publications() -> None:
    observed = play("2021-12-31T12:00:00")
    query = ListeningQuery(date(2024, 1, 1), date(2024, 1, 1), "UTC")
    result = listening_anniversaries(
        (observed,), query, (observed.timestamp_ms, observed.timestamp_ms)
    )
    assert [item.covered for item in result.days] == [False, False, False]
    assert all(item.plays == 0 for item in result.days)
    empty = listening_anniversaries((), query, (None, None))
    assert empty.days == () and empty.observed_from is None
    assert empty.observed_through is None


def test_anniversary_top_five_is_bounded_and_uses_whole_day_denominator() -> None:
    plays = []
    for index in range(7):
        plays.append(play("2020-05-01T12:00:00", str(index)))
    query = ListeningQuery(date(2021, 5, 1), date(2021, 5, 1), "UTC")
    bounds = plays[0].timestamp_ms, plays[-1].timestamp_ms
    day = listening_anniversaries(tuple(plays), query, bounds).days[0]
    assert day.plays == 7 and day.artists == 7
    assert len(day.top_artists) == 5
    assert day.top_artists[0].share == pytest.approx(1 / 7)
