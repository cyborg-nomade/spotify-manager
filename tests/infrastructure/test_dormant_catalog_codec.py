"""Protect original liked-response cardinality and popularity metadata tolerance."""

import pytest

from spotify_manager.application.dormant_values import BlastFromPastArtistsError
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.infrastructure.dormant_catalog import liked_statuses
from spotify_manager.infrastructure.dormant_catalog import popularity_details


TRACK = CatalogTrack("track", "uri", "Song", 1, 1, "artist", "Artist", 50)


@pytest.mark.parametrize("raw", [None, (), {}, [], [True, False]])
def test_liked_response_requires_exact_original_list(raw: object) -> None:
    """Reject original wrong shape or cardinality without inventing statuses.

    Args:
        raw: Original untrusted response.
    """
    with pytest.raises(BlastFromPastArtistsError, match="Liked Songs statuses"):
        liked_statuses(raw, (TRACK,))


def test_liked_response_retains_original_truthiness_and_duplicate_overwrite() -> None:
    """Retain last truthiness for repeated identities and empty-list tolerance."""
    assert liked_statuses(["yes", None], (TRACK, TRACK)) == {"track": False}
    assert liked_statuses([], ()) == {}


@pytest.mark.parametrize("raw", [None, [], {}, {"tracks": None}])
def test_popularity_response_requires_original_details_list(raw: object) -> None:
    """Reject missing original detail lists.

    Args:
        raw: Original untrusted response.
    """
    with pytest.raises(BlastFromPastArtistsError, match="liked-track details"):
        popularity_details(raw, {"track": TRACK})


def test_popularity_preserves_order_duplicates_and_bool_integer_tolerance() -> None:
    """Retain unknown rows, coerced identity and original integer-only popularity."""
    raw = {
        "tracks": [
            None,
            {"id": "unknown"},
            {"id": None},
            {"id": " track ", "popularity": True},
            {"id": "track", "popularity": "99"},
        ]
    }
    details = popularity_details(raw, {"track": TRACK})
    assert [track.popularity for track in details] == [True, None]
    assert [track.spotify_id for track in details] == ["track", "track"]
    assert TRACK.popularity == 50
