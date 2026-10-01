"""Protect permissive Queue cache decoding and actual-addition log filtering."""

import json
from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.domain.queue_candidates import LastFmSimilarArtist
from spotify_manager.infrastructure.queue_neighborhoods import added_artist_keys
from spotify_manager.infrastructure.queue_neighborhoods import cached_artists


WEEK = date(2026, 8, 7)


def _week(timestamp: datetime) -> date:
    assert timestamp.tzinfo == UTC
    return date(2026, 8, 7) if timestamp.day == 8 else date(2026, 8, 14)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"fetched_at": "bad"},
        {"fetched_at": "2026-08-15T00:00:00Z", "artists": []},
        {"fetched_at": "2026-08-08T00:00:00Z"},
        {"fetched_at": "2026-08-08T00:00:00Z", "artists": {}},
        {"fetched_at": "2026-08-08T00:00:00Z", "artists": [{}]},
        {"fetched_at": "2026-08-08T00:00:00Z", "artists": [{"artist": "A"}]},
        {
            "fetched_at": "2026-08-08T00:00:00Z",
            "artists": [{"artist": "A", "match": None}],
        },
        {
            "fetched_at": "2026-08-08T00:00:00Z",
            "artists": [{"artist": "A", "match": "bad"}],
        },
    ],
)
def test_original_cache_misses(raw: object) -> None:
    """Keep malformed or expired records as misses without stricter errors.

    Args:
        raw: Original unchecked malformed or expired record.
    """
    assert cached_artists(raw, WEEK, _week) is None


@pytest.mark.parametrize("timestamp", ["2026-08-08T00:00:00", "2026-08-08T00:00:00Z"])
def test_cache_coercions_and_nondict_rows(timestamp: str) -> None:
    """Preserve UTC defaults, skipped nonrecords and original field coercions.

    Args:
        timestamp: Original naive or aware current-week timestamp.
    """
    raw: dict[str, object] = {
        "fetched_at": timestamp,
        "artists": [None, [], {"artist": 12, "match": "0.5"}],
    }
    assert cached_artists(raw, WEEK, _week) == (LastFmSimilarArtist("12", 0.5),)


def test_cache_valid_empty_observation_is_hit() -> None:
    """Keep a current-week empty neighborhood reusable without a network read."""
    assert (
        cached_artists(
            {"fetched_at": "2026-08-08T00:00:00Z", "artists": []}, WEEK, _week
        )
        == ()
    )


def test_log_records_only_actual_additions() -> None:
    """Keep previews, blanks, nonrecords and falsey keys out of actual additions."""
    lines = [
        "",
        "  ",
        "null",
        "[]",
        '{"event":"fill_candidate","lastfm_artist_key":"preview"}',
        '{"event":"artist_added","lastfm_artist_key":" A "}',
        '{"event":"artist_added","lastfm_artist_key":"A"}',
        '{"event":"artist_added","lastfm_artist_key":12}',
        '{"event":"artist_added","lastfm_artist_key":0}',
        '{"event":"artist_added","lastfm_artist_key":" "}',
    ]
    assert added_artist_keys(lines) == {"A", "12"}


def test_log_invalid_line_preserves_decoder_failure() -> None:
    """Stop on the original malformed physical line without silently truncating."""
    with pytest.raises(json.JSONDecodeError):
        added_artist_keys(['{"event":"artist_added","lastfm_artist_key":"A"}', "bad"])
