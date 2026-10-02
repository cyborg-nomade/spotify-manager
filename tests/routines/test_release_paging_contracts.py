"""Protect original release, track and destination pagination at the SDK boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import cast

import pytest
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.routines import release_check as legacy
from tests.support.release_run import ARTIST
from tests.support.release_run import release


@dataclass
class Pages:
    """Return explicit pages or SDK errors and record each requested offset.

    Args:
        responses: Ordered untrusted SDK pages or errors.
    """

    responses: list[object]
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def _read(self, *request: object) -> object:
        self.calls.append(request)
        response = self.responses[len(self.calls) - 1]
        if isinstance(response, SpotifyException):
            raise response
        return response

    def artist_albums(
        self, artist_id: str, *, include_groups: str, limit: int, offset: int
    ) -> object:
        """Read an original catalog page.

        Args:
            artist_id: Original artist identity.
            include_groups: Original catalog groups.
            limit: Original page size.
            offset: Original ordered offset.

        Returns:
            Explicit untrusted page.
        """
        return self._read(artist_id, include_groups, limit, offset)

    def album_tracks(self, release_id: str, *, limit: int, offset: int) -> object:
        """Read an original track page.

        Args:
            release_id: Original release identity.
            limit: Original first-only or full page size.
            offset: Original ordered offset.

        Returns:
            Explicit untrusted page.
        """
        return self._read(release_id, limit, offset)

    def _get(self, endpoint: str, *, limit: int, offset: int) -> object:
        return self._read(endpoint, limit, offset)


def _raw_release(
    identifier: str, stamp: str, artist_id: str = ARTIST.spotify_id
) -> dict[str, object]:
    return {
        "id": identifier,
        "uri": "spotify:album:" + identifier,
        "name": identifier,
        "album_type": "album",
        "release_date": stamp,
        "release_date_precision": "day",
        "total_tracks": 10,
        "artists": [{"id": artist_id, "name": ARTIST.name}],
    }


def _raw_track(identifier: str, position: object = None) -> dict[str, object]:
    return {
        "id": identifier,
        "uri": "spotify:track:" + identifier,
        "name": identifier,
        "track_number": position,
        "disc_number": 1,
        "artists": [{"id": ARTIST.spotify_id, "name": ARTIST.name}],
    }


def _retry(operation: Callable[[], object], description: str) -> object:
    return operation()


@pytest.mark.parametrize("kind", ["release", "track", "playlist"])
@pytest.mark.parametrize("page", [None, {}, {"items": None}, {"items": {}}])
def test_original_paging_rejects_invalid_page_shape(kind: str, page: object) -> None:
    """Reject missing/nonlist pages without issuing another request.

    Args:
        kind: Original endpoint kind.
        page: Malformed untrusted response.
    """
    pages = Pages([page])
    with pytest.raises(
        legacy.ReleaseCheckSpotifyError, match="invalid " + kind + " data"
    ):
        _load(kind, pages)
    assert len(pages.calls) == 1


def _load(kind: str, pages: Pages) -> object:
    spotify = cast(Spotify, pages)
    if kind == "release":
        return legacy.load_recent_catalog(
            spotify,
            legacy.RankedArtist("artist", "Artist", 100, 1),
            ARTIST,
            date(2026, 1, 1),
            _retry,
        )
    if kind == "track":
        return legacy.load_release_tracks(spotify, release(), _retry)
    return legacy._playlist_snapshot(spotify, "playlist", _retry)


@pytest.mark.parametrize("kind", ["release", "track", "playlist"])
def test_original_paging_rejects_empty_continuation(kind: str) -> None:
    """Reject empty pages advertising continuation without a repeated offset read.

    Args:
        kind: Original endpoint kind.
    """
    pages = Pages([{"items": [], "next": "next"}])
    with pytest.raises(
        legacy.ReleaseCheckSpotifyError, match="empty " + kind + " page"
    ):
        _load(kind, pages)
    assert len(pages.calls) == 1


def test_original_catalog_scans_old_and_invalid_pages_and_replaces_duplicate_ids() -> (
    None
):
    """Scan every page, replace duplicate metadata and sort final observations."""
    first = [
        _raw_release("old", "2025-12-31"),
        _raw_release("bad", "invalid"),
        _raw_release("wrong", "2026-05-01", "other"),
        _raw_release("same", "2026-09-01"),
    ]
    second = [_raw_release("same", "2026-08-01"), _raw_release("future", "2027-01-01")]
    pages = Pages([{"items": first, "next": "next"}, {"items": second}])
    result = cast(tuple[legacy.ReleaseCandidate, ...], _load("release", pages))
    assert [(item.spotify_id, item.release_date) for item in result] == [
        ("same", "2026-08-01"),
        ("future", "2027-01-01"),
    ]
    assert pages.calls == [
        (ARTIST.spotify_id, "album,single", 10, 0),
        (ARTIST.spotify_id, "album,single", 10, 4),
    ]


def test_original_tracks_use_accepted_marker_count_for_fallback_positions() -> None:
    """Skip unplayable rows and sort playable markers after offset pagination."""
    pages = Pages(
        [
            {"items": [None, _raw_track("second", 2)], "next": "next"},
            {"items": [_raw_track("fallback"), _raw_track("first", 1)]},
        ]
    )
    result = cast(tuple[legacy.ReleaseTrack, ...], _load("track", pages))
    assert [(track.spotify_id, track.track_number) for track in result] == [
        ("first", 1),
        ("second", 2),
        ("fallback", 2),
    ]
    assert pages.calls == [("release", 50, 0), ("release", 50, 2)]


def test_original_first_only_tracks_do_not_follow_even_an_empty_continuation() -> None:
    """A first-only empty response returns empty without continuation validation."""
    pages = Pages([{"items": [], "next": "next"}])
    assert (
        legacy.load_release_tracks(
            cast(Spotify, pages), release(), _retry, first_only=True
        )
        == ()
    )
    assert pages.calls == [("release", 1, 0)]


@pytest.mark.parametrize("after_page", [False, True])
def test_original_track_404_discards_any_previous_page(after_page: bool) -> None:
    """A missing track endpoint returns empty even after previously accepted pages.

    Args:
        after_page: Return one playable page before the missing endpoint.
    """
    responses: list[object] = []
    if after_page:
        responses.append({"items": [_raw_track("first")], "next": "next"})
    responses.append(SpotifyException(404, -1, "missing"))
    pages = Pages(responses)
    assert _load("track", pages) == ()
    assert len(pages.calls) == (2 if after_page else 1)


def test_original_track_non_404_sdk_error_is_propagated() -> None:
    """Retain the original SDK error identity for every non-404 failure."""
    original = SpotifyException(429, -1, "limited")
    with pytest.raises(SpotifyException) as error:
        _load("track", Pages([original]))
    assert error.value is original


def test_original_playlist_total_can_require_pages_without_next() -> None:
    """Follow integer totals and preserve URI-only entries and their original order."""
    pages = Pages(
        [
            {"items": [{"item": {"uri": "spotify:track:opaque"}}], "total": 2},
            {"items": [{"track": _raw_track("second")}], "total": 2},
        ]
    )
    snapshot = cast(legacy.PlaylistSnapshot, _load("playlist", pages))
    assert [entry.uri for entry in snapshot.entries] == [
        "spotify:track:opaque",
        "spotify:track:second",
    ]
    assert pages.calls == [
        ("playlists/playlist/items", 50, 0),
        ("playlists/playlist/items", 50, 1),
    ]


@pytest.mark.parametrize("item", [None, {}, {"item": {}}, {"item": "invalid"}])
def test_original_playlist_unpreservable_item_is_fatal(item: object) -> None:
    """An unpreservable playlist row fails before later page reads.

    Args:
        item: Untrusted playlist entry.
    """
    pages = Pages([{"items": [item], "next": "next"}])
    with pytest.raises(
        legacy.ReleaseCheckSpotifyError, match="cannot be preserved safely"
    ):
        _load("playlist", pages)
    assert len(pages.calls) == 1
