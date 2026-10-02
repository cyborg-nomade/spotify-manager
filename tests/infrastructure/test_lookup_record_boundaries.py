"""Protect tolerant catalog parsing and distinct pagination error contracts."""

import pytest

from spotify_manager.domain.lookup_values import SpotifyLookupResponseError
from spotify_manager.infrastructure import lookup_catalog as catalog
from spotify_manager.infrastructure import lookup_records as records
from spotify_manager.infrastructure.scrobble_lookup import latest_timestamp
from tests.support.library_lookup_run import raw_track


@pytest.mark.parametrize("raw", [None, {}, {"artists": []}, {"artists": [None]}])
def test_incomplete_primary_credit_is_absent(raw: object) -> None:
    """Preserve missing first-credit identities.

    Args:
        raw: Original unchecked response row.
    """
    assert records.primary_artist_id(raw) is None


@pytest.mark.parametrize("raw", [None, {}, {"name": " "}])
def test_optional_album_name_remains_optional(raw: object) -> None:
    """Keep incomplete optional metadata out of track identities.

    Args:
        raw: Original unchecked album metadata.
    """
    assert records._optional_album_name(raw) is None


def test_track_metadata_and_popularity_are_not_tightened() -> None:
    """Keep integer booleans and tolerate malformed optional album metadata."""
    raw = raw_track("track")
    raw["popularity"] = True
    raw["album"] = None
    parsed = records.track(raw)
    assert parsed is not None and parsed.popularity is True and parsed.album is None
    raw["artists"] = []
    assert records.track(raw) is None
    raw["artists"] = [{"name": ""}]
    assert records.track(raw) is None
    assert records.live_albums([None, {"id": "album"}])[0].spotify_id == "album"


def test_incomplete_minimized_display_fails_after_pagination() -> None:
    """Require the same display fields at the original final minimization stage."""
    with pytest.raises(SpotifyLookupResponseError, match="incomplete track"):
        records.minimized_track({"name": "Title"}, "album")


def no_next(page: object) -> object:
    """Reject an unexpected dependent read.

    Args:
        page: Previous raw page.

    Raises:
        AssertionError: The fixture unexpectedly follows a continuation.
    """
    raise AssertionError(page)


def album_batch(ids: list[str]) -> object:
    """Return missing album rows followed by a valid empty page.

    Args:
        ids: Ordered requested identities.

    Returns:
        Original raw batch shape.
    """
    assert ids == ["album"]
    return {"albums": [None, {"tracks": {"items": [], "next": None}}]}


def test_primary_catalog_skips_missing_and_empty_id_rows() -> None:
    """Filter first credits before requiring an identity or dependent page."""
    rows: list[object] = [{"artists": [{"id": "artist"}]}]
    assert catalog.primary_ids(rows, "artist") == []
    assert catalog.primary_tracks(album_batch, no_next, "artist", ["album"], 20) == []
    with pytest.raises(SpotifyLookupResponseError, match="empty album track page"):
        catalog.album_primary_tracks({"items": [], "next": "more"}, no_next, "artist")


def test_history_selects_greatest_timestamp_and_ignores_older_encounters() -> None:
    """Keep the greatest play rather than the last matching row."""
    rows: list[object] = [
        {"artist": "artist", "track": "track", "date": 2000},
        {"artist": "artist", "track": "track", "date": 1000},
    ]
    assert latest_timestamp(rows, "track", "artist") == 2000
