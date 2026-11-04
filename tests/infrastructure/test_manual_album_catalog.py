"""Broad album searches expose usable observations without automatic filtering."""

from typing import cast
from unittest.mock import AsyncMock

import pytest

from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.ports.runtime import NO_RETRY
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure.manual_album_catalog import SpotifyManualAlbums
from tests.support.manual_matching import CatalogChoices


def _raw(identity: str) -> dict[str, object]:
    return {
        "id": identity,
        "name": "Different title",
        "album_type": "compilation",
        "artists": [
            {"id": "other", "name": "Other artist"},
            {"id": "guest", "name": "Guest"},
        ],
        "release_date": "2020",
        "total_tracks": 20,
    }


@pytest.mark.parametrize("track_search", [False, True])
async def test_album_candidates_preserve_first_ten_search_positions(
    track_search: bool,
) -> None:
    """Show complete album credits even when title, artist or release type differs.

    Args:
        track_search: Resolve a recommended track to album candidates when true.
    """
    client = AsyncMock()
    rows = [_raw(str(index)) for index in range(12)]
    if track_search:
        rows = [
            {"id": f"track-{index}", "name": "Source", "album": row}
            for index, row in enumerate(rows)
        ]
    key = "tracks" if track_search else "albums"
    client.search.return_value = {key: {"items": rows}}
    play = Scrobble(
        "Song" if track_search else "", "Artist", "" if track_search else "Album", 0
    )
    albums = await SpotifyManualAlbums(
        cast(SpotifyClient, client), NO_RETRY, CatalogChoices()
    ).search(play)
    assert [album.spotify_id for album in albums] == [str(index) for index in range(10)]
    assert albums[0].artists == ("Other artist", "Guest")
    assert albums[0].release_type == "compilation"
    assert albums[0].source_track_id == ("track-0" if track_search else "")
    client.search.assert_awaited_once_with(
        q="Artist Song" if track_search else "Artist Album",
        type="track" if track_search else "album",
        limit=10,
        offset=0,
    )


@pytest.mark.parametrize(
    "response", [None, {}, {"albums": []}, {"albums": {"items": None}}]
)
async def test_invalid_album_pages_propagate_as_errors(response: object) -> None:
    """Do not turn malformed responses into explicit no-match decisions.

    Args:
        response: Malformed external response.
    """
    client = AsyncMock()
    client.search.return_value = response
    with pytest.raises(SpotifyTrackResolutionError, match="invalid manual album"):
        await SpotifyManualAlbums(
            cast(SpotifyClient, client), NO_RETRY, CatalogChoices()
        ).search(Scrobble("", "Artist", "Album", 0))


async def test_album_parser_skips_invalid_rows_and_duplicate_editions_in_order() -> (
    None
):
    """Retain first encounter rank without filling from beyond the top ten."""
    client = AsyncMock()
    client.search.return_value = {
        "albums": {"items": [None, {}, _raw("same"), _raw("same"), _raw("next")]}
    }
    albums = await SpotifyManualAlbums(
        cast(SpotifyClient, client), NO_RETRY, CatalogChoices()
    ).search(Scrobble("", "Artist", "Album", 0))
    assert [album.spotify_id for album in albums] == ["same", "next"]
    assert [album.search_rank for album in albums] == [3, 5]


async def test_album_credits_retain_names_without_artist_identifiers() -> None:
    """Show every named credit even when Spotify omits an artist identity."""
    client = AsyncMock()
    album = _raw("album")
    album["artists"] = [
        {"id": "primary", "name": "Primary"},
        {"name": "Guest"},
    ]
    client.search.return_value = {"albums": {"items": [album]}}
    albums = await SpotifyManualAlbums(
        cast(SpotifyClient, client), NO_RETRY, CatalogChoices()
    ).search(Scrobble("", "Artist", "Album", 0))
    assert albums[0].artists == ("Primary", "Guest")
    assert albums[0].artist_ids == ("primary", "")
