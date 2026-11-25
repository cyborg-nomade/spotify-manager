"""Read tracklists only for known Spotify editions from a pinned publication."""

import asyncio
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from spotify_manager.domain.listening_library_values import LibraryCatalog


@dataclass(frozen=True)
class RediscoveryTrack:
    """Keep Spotify's track name, playlist identity and album position."""

    uri: str
    name: str
    disc: int
    track: int


@dataclass(frozen=True)
class RediscoveryTracklist:
    """Keep one complete album or explain why it could not be loaded."""

    uri: str
    tracks: tuple[RediscoveryTrack, ...] = ()
    message: str | None = None


@dataclass(frozen=True)
class RediscoveryTracklists:
    """Report each selected edition in the same order as the request."""

    library_snapshot: str
    albums: tuple[RediscoveryTracklist, ...]


class AlbumTracklistReads(Protocol):
    """Read one complete Spotify album without playlist or library writes."""

    async def read(self, uri: str) -> RediscoveryTracklist:
        """Return the tracklist or a recoverable per-album failure."""
        ...


class AlbumPublicationError(ValueError):
    """Report album editions outside the pinned complete saved-album mirror."""


@lru_cache(maxsize=4)
def _saved_album_uris(catalog: LibraryCatalog) -> frozenset[str]:
    return frozenset(entry.uri for entry in catalog.entries if entry.kind == "album")


async def get_rediscovery_tracklists(
    catalog: LibraryCatalog, choices: tuple[str, ...], source: AlbumTracklistReads
) -> RediscoveryTracklists:
    """Read complete album tracklists for selected saved editions.

    Args:
        catalog: Pinned Spotify library mirror.
        choices: Unique Spotify album URIs in playlist order.
        source: Read-only Spotify tracklist resource.

    Returns:
        Ordered results with recoverable failures confined to the affected albums.

    Raises:
        AlbumPublicationError: An edition could not be verified in the mirror.
    """
    if not set(choices).issubset(_saved_album_uris(catalog)):
        raise AlbumPublicationError(
            "Choose albums in the current saved-album publication."
        )
    rows = await asyncio.gather(*(source.read(uri) for uri in choices))
    return RediscoveryTracklists(catalog.snapshot, tuple(rows))
