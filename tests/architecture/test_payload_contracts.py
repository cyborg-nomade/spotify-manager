"""Keep static SDK narrowing from adding validation, coercion or payload copies."""

from dataclasses import dataclass

import pytest

from spotify_manager.application.ports.spotify_async import SpotifyJson
from spotify_manager.application.ports.spotify_async import SpotifyRequest
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.processors.your_library_processors import (
    async_is_in_library_artist,
)
from spotify_manager.processors.your_library_processors import async_is_in_library_track
from spotify_manager.routines.convert_library_file import _analyse_added
from spotify_manager.routines.convert_library_file import _analyse_removed
from spotify_manager.routines.convert_library_file import _contains_added
from spotify_manager.routines.convert_library_file import _contains_removed


@dataclass(frozen=True)
class JsonReply:
    """Return one unchecked endpoint value without an HTTP or SDK dependency.

    Args:
        value: Original JSON value, including malformed endpoint responses.
    """

    value: SpotifyJson

    async def request(self, request: SpotifyRequest) -> SpotifyJson:
        """Retain the original value and object identity.

        Args:
            request: Explicit native endpoint request.

        Returns:
            Original response object with no validation or copy.
        """
        return self.value


async def _membership(client: AsyncSpotify, resource: str) -> object:
    if resource == "artists":
        artist = YourLibraryArtist(name="Artist", uri="spotify:artist:artist")
        return await async_is_in_library_artist(client, artist)
    track = YourLibraryTrack(
        artist="Artist", album="Album", track="Track", uri="spotify:track:track"
    )
    return await async_is_in_library_track(client, track)


@pytest.mark.parametrize("resource", ["artists", "tracks"])
@pytest.mark.parametrize("value", [False, True, 1, "original truthy value"])
async def test_membership_annotation_does_not_coerce_original_values(
    resource: str, value: SpotifyJson
) -> None:
    """Preserve even malformed truthy SDK values instead of silently making bools.

    Args:
        resource: Original follow or liked-track endpoint.
        value: Original first response element.
    """
    result = await _membership(AsyncSpotify(JsonReply([value])), resource)
    assert result is value


@pytest.mark.parametrize("resource", ["artists", "tracks"])
@pytest.mark.parametrize(
    "value,error",
    [(None, TypeError), ([], IndexError), ({}, KeyError)],
)
async def test_membership_narrowing_preserves_native_indexing_errors(
    resource: str, value: SpotifyJson, error: type[Exception]
) -> None:
    """Type hints must not replace the original failure or tolerate an empty result.

    Args:
        resource: Original follow or liked-track endpoint.
        value: Malformed original response.
        error: Original direct-indexing failure.
    """
    with pytest.raises(error):
        await _membership(AsyncSpotify(JsonReply(value)), resource)


async def test_legacy_comparison_memberships_retain_the_first_value() -> None:
    """All four public compatibility paths retain unchecked singleton membership."""
    client = AsyncSpotify(JsonReply(["unchanged"]))
    assert await _analyse_added(client, "album") == "unchanged"
    assert await _analyse_removed(client, "album") == "unchanged"
    assert await _contains_added(client, "album") == "unchanged"
    assert await _contains_removed(client, "album") == "unchanged"
