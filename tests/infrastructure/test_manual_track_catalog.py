"""Broad search keeps low-similarity results and rejects unusable response shapes."""

from typing import cast
from unittest.mock import AsyncMock

import pytest

from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.application.ports.runtime import NO_RETRY
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure.manual_track_catalog import SpotifyManualTracks
from tests.application.test_manual_track_matching import ManualScript
from tests.routines.test_daily_mind_radio import spotify_track


@pytest.mark.parametrize("album", ["Album", "", None])
async def test_broad_search_uses_available_text_and_retains_first_ten_in_order(
    album: str | None,
) -> None:
    """Retain all artist credits and search rank without qualification filtering.

    Args:
        album: Available historical album text, including absent values.
    """
    client = AsyncMock()
    rows = []
    for index in range(12):
        row = spotify_track(
            str(index), "Unrelated", "Different artist", "Different album", 1
        )
        row["artists"] = [{"name": "Different artist"}, {"name": "Guest"}]
        rows.append(row)
    client.search.return_value = {"tracks": {"items": rows}}
    scrobble = Scrobble("Song", "Artist", album, 1)
    result = await SpotifyManualTracks(
        cast(SpotifyClient, client), NO_RETRY, ManualScript()
    ).search(scrobble)
    client.search.assert_awaited_once_with(
        q="Artist Song" + (" Album" if album else ""), type="track", limit=10, offset=0
    )
    assert [candidate.spotify_id for candidate in result] == [
        str(index) for index in range(10)
    ]
    assert result[0].artists == ("Different artist", "Guest")
    assert result[0].album == "Different album"
    assert result[0].track_similarity < 0.9
    if album:
        assert result[0].album_similarity is not None
        assert result[0].album_similarity < 0.9
    else:
        assert result[0].album_similarity is None


@pytest.mark.parametrize(
    "response", [None, [], {}, {"tracks": []}, {"tracks": {"items": None}}]
)
async def test_malformed_search_is_an_error_instead_of_no_match(
    response: object,
) -> None:
    """Distinguish a malformed response from a valid empty search.

    Args:
        response: Malformed external search response.
    """
    client = AsyncMock()
    client.search.return_value = response
    with pytest.raises(SpotifyTrackResolutionError, match="invalid manual search"):
        await SpotifyManualTracks(
            cast(SpotifyClient, client), NO_RETRY, ManualScript()
        ).search(Scrobble("Song", "Artist", "", 1))


async def test_incomplete_results_are_skipped_without_filling_from_below_top_ten() -> (
    None
):
    """Skip unusable rows without moving results into the original top ten."""
    client = AsyncMock()
    row = spotify_track("valid", "Title", "Artist", "Album", 1)
    row.pop("uri")
    row["album"] = None
    row["popularity"] = "unknown"
    client.search.return_value = {
        "tracks": {"items": [None, {}, {"id": "no-title"}, row]}
    }
    result = await SpotifyManualTracks(
        cast(SpotifyClient, client), NO_RETRY, ManualScript()
    ).search(Scrobble("Song", "Artist", "Album", 1))
    assert len(result) == 1
    assert result[0].uri == "spotify:track:valid"
    assert result[0].search_rank == 4
    assert result[0].album == ""
    assert result[0].popularity is None
