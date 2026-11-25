"""Freeze rediscovery's calendar edges and artist eligibility rules."""

from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.domain.listening_rediscovery import ArtistRevisitEvidence
from spotify_manager.domain.listening_rediscovery import RediscoveryRules
from spotify_manager.domain.listening_rediscovery import RediscoveryWindowError
from spotify_manager.domain.listening_rediscovery import rank_rediscovery_artists
from spotify_manager.domain.listening_rediscovery import rediscovery_dates
from spotify_manager.domain.listening_values import ListeningQuery


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


def test_recent_coverage_and_leap_day_keep_nonoverlapping_windows() -> None:
    """Use complete local archive days and move leap day within its prior month."""
    query = ListeningQuery(date(2023, 1, 1), date(2024, 3, 31), "Europe/Berlin")
    rules = RediscoveryRules(30, True, 50, 3)
    latest = _ms("2024-03-29T23:10:00")
    dates = rediscovery_dates(query, rules, (_ms("2022-01-01"), latest))
    assert dates.recent.start == date(2024, 2, 29)
    assert dates.recent.end == date(2024, 3, 29)
    assert dates.historical.start == date(2023, 2, 28)
    assert dates.historical.end == date(2024, 2, 28)
    assert dates.recent_complete
    incomplete = rediscovery_dates(query, rules, (_ms("2024-02-29"), latest))
    empty = rediscovery_dates(query, rules, (None, None))
    assert not incomplete.recent_complete and not empty.recent_complete
    with pytest.raises(RediscoveryWindowError, match="before the recent window"):
        rediscovery_dates(
            query, RediscoveryRules(30, False, 50, 3), (_ms("2022-01-01"), latest)
        )


def test_dormancy_beats_an_incidental_play_and_weeks_beat_catalog_size() -> None:
    """Give repeat weeks precedence and exclude several recent tracks or days."""
    artists = (
        ArtistRevisitEvidence("bulk", "Big catalog", 200, 1, 0, 0, 0),
        ArtistRevisitEvidence("deep", "Returned often", 150, 5, 0, 0, 0),
        ArtistRevisitEvidence("regular", "Returned weekly", 55, 9, 0, 0, 0),
        ArtistRevisitEvidence("minor", "One recent track", 100, 25, 2, 1, 1),
        ArtistRevisitEvidence("again", "Two days", 100, 20, 2, 2, 1),
        ArtistRevisitEvidence("album", "Three tracks", 100, 20, 3, 1, 3),
        ArtistRevisitEvidence("new", "Low total", 49, 20, 0, 0, 0),
    )
    rules = RediscoveryRules(90, True, 50, 3)
    assert [row.key for row in rank_rediscovery_artists(artists, rules)] == [
        "regular",
        "deep",
        "minor",
    ]
