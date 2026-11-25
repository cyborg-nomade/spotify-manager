"""Read complete paginated Spotify albums with bounded concurrency and time."""

import asyncio
import re
from typing import Protocol

import httpx
from pydantic import ValidationError
from spotipy.exceptions import SpotifyException

from spotify_manager.application.listening_album_tracklists import RediscoveryTrack
from spotify_manager.application.listening_album_tracklists import RediscoveryTracklist


_TRACK_URI = re.compile(r"spotify:track:[A-Za-z0-9]{22}")
_PAGE_SIZE = 50
_MAX_TRACKS = 1000


class AlbumPages(Protocol):
    """Read one page from the Spotify album-track endpoint."""

    async def album_tracks(self, album_id: str, *, limit: int, offset: int) -> object:
        """Return raw Spotify album track data for validation."""
        ...


class AlbumClientOwner(Protocol):
    """Acquire the lifespan-owned Spotify client when an album is requested."""

    async def client(self) -> AlbumPages:
        """Return the shared Spotify client on the owning event loop."""
        ...


class SpotifyAlbumTracklists:
    """Provide complete tracklists for the Listening Explorer's playlist preview."""

    def __init__(self, owner: AlbumClientOwner) -> None:
        """Bind the existing runtime and bound concurrent tracklist reads.

        Args:
            owner: Lifespan owner of the authenticated Spotify client.
        """
        self._owner = owner
        self._reads = asyncio.Semaphore(3)

    async def read(self, uri: str) -> RediscoveryTracklist:
        """Read one edition in recorded disc and track-number order.

        Args:
            uri: Validated Spotify album URI in the pinned saved collection.

        Returns:
            Complete playlistable album rows or a recoverable explanation.
        """
        try:
            async with self._reads, asyncio.timeout(12):
                client = await self._owner.client()
                tracks = await _album_tracks(client, uri.rsplit(":", 1)[-1])
        except (
            SpotifyException,
            httpx.HTTPError,
            TimeoutError,
            ValidationError,
            OSError,
            RuntimeError,
        ):
            return RediscoveryTracklist(
                uri, message="Spotify could not load this album. Try again."
            )
        except ValueError:
            return RediscoveryTracklist(
                uri, message="Spotify did not return a complete playable tracklist."
            )
        return RediscoveryTracklist(uri, tracks)


def _track(raw: object) -> RediscoveryTrack:
    if isinstance(raw, dict):
        uri, name = raw.get("uri"), raw.get("name")
        disc, number = raw.get("disc_number"), raw.get("track_number")
        if (
            isinstance(uri, str)
            and _TRACK_URI.fullmatch(uri)
            and isinstance(name, str)
            and name.strip()
            and type(disc) is int
            and disc > 0
            and type(number) is int
            and number > 0
            and raw.get("is_playable") is not False
            and not raw.get("is_local")
        ):
            return RediscoveryTrack(uri, name, disc, number)
    raise ValueError("Invalid Spotify track row.")


def _page(raw: object, offset: int) -> tuple[list[object], int]:
    if not isinstance(raw, dict):
        raise ValueError("Invalid Spotify track page.")
    rows, total = raw.get("items"), raw.get("total")
    if (
        not isinstance(rows, list)
        or not rows
        or len(rows) > _PAGE_SIZE
        or type(total) is not int
        or total > _MAX_TRACKS
        or raw.get("offset") != offset
        or offset + len(rows) > total
        or bool(raw.get("next")) != (offset + len(rows) < total)
    ):
        raise ValueError("Invalid Spotify track page coverage.")
    return rows, total


async def _album_tracks(
    client: AlbumPages, identifier: str
) -> tuple[RediscoveryTrack, ...]:
    tracks: list[RediscoveryTrack] = []
    total = None
    while total is None or len(tracks) < total:
        raw = await client.album_tracks(
            identifier, offset=len(tracks), limit=_PAGE_SIZE
        )
        rows, size = _page(raw, len(tracks))
        if total is not None and size != total:
            raise ValueError("The Spotify tracklist changed during pagination.")
        total = size
        tracks.extend(_track(row) for row in rows)
    positions = {(track.disc, track.track) for track in tracks}
    if len(positions) != len(tracks):
        raise ValueError("The Spotify tracklist has conflicting positions.")
    return tuple(sorted(tracks, key=_position))


def _position(track: RediscoveryTrack) -> tuple[int, int]:
    return track.disc, track.track
