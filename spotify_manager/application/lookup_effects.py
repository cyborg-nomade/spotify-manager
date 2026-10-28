"""Explicit raw catalog, cache and history boundaries for original lookups."""

from dataclasses import dataclass
from typing import Protocol
from typing import TypedDict

from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.models.your_library import YourLibraryFile


class LookupTrack(TypedDict):
    """Unchecked original minimized track fields; validation remains at presentation."""

    id: str | None
    name: str
    uri: str


@dataclass(frozen=True)
class LookupPage:
    """Original validated container with unchecked row values.

    Args:
        rows: Every original raw row, including non-objects.
        next: Original next-link value without new validation.
    """

    rows: list[object]
    next: object


class CachedTracks(Protocol):
    """Read and publish track caches, acquiring a client only on a cache miss."""

    async def load(self) -> dict[str, list[LookupTrack]]:
        """Read the cache.

        Returns:
            Unchecked cached track lists.
        """
        ...

    async def save(self, cache: dict[str, list[LookupTrack]]) -> None:
        """Publish the complete cache.

        Args:
            cache: Complete accepted cache.
        """
        ...

    async def fetch(self, identifier: str) -> list[LookupTrack]:
        """Read every live track page.

        Args:
            identifier: Album identity.

        Returns:
            Complete minimized tracks.
        """
        ...


class LocalLibrary(Protocol):
    """Read the local export authority."""

    async def library(self) -> YourLibraryFile:
        """Read local library facts.

        Returns:
            Complete export.
        """
        ...


@dataclass(frozen=True)
class LocalAlbumLookup:
    """Supply export and track authorities without concealing a cache use case.

    Args:
        files: Export reader.
        tracks: Cache and live track reader.
        use_cache: Whether cache reads and publication are enabled.
        refresh_cache: Whether to bypass a cache hit.
    """

    files: LocalLibrary
    tracks: CachedTracks
    use_cache: bool
    refresh_cache: bool


class ArtistLookup(Protocol):
    """Observe direct and searched artist identities."""

    async def direct(self, identifier: str) -> tuple[str, str] | None:
        """Read direct metadata.

        Args:
            identifier: Artist identity.

        Returns:
            Complete identity, or none for incomplete metadata.
        """
        ...

    async def search(self, name: str) -> list[tuple[str, str]]:
        """Read name candidates.

        Args:
            name: Exact artist reference.

        Returns:
            Candidates in encounter order.
        """
        ...


class AlbumLookup(Protocol):
    """Observe direct and searched album metadata."""

    async def direct(self, identifier: str) -> LiveAlbumCandidate:
        """Read direct metadata.

        Args:
            identifier: Album identity.

        Returns:
            Album candidate.
        """
        ...

    async def search(self, name: str, artist: str | None) -> list[LiveAlbumCandidate]:
        """Read name candidates.

        Args:
            name: Exact title.
            artist: Optional primary-artist constraint.

        Returns:
            Candidates in encounter order.
        """
        ...


class TrackLookup(Protocol):
    """Observe direct and searched track metadata."""

    async def direct(self, identifier: str) -> ResolvedTrack:
        """Read direct metadata.

        Args:
            identifier: Track identity.

        Returns:
            Track metadata.
        """
        ...

    async def search(self, name: str) -> list[ResolvedTrack]:
        """Read title candidates.

        Args:
            name: Exact title.

        Returns:
            Candidates in encounter order.
        """
        ...


class LookupMembership(Protocol):
    """Observe fresh membership statuses for an ordered batch."""

    async def contains(self, identifiers: list[str]) -> object:
        """Read a membership batch.

        Args:
            identifiers: Ordered identities, retaining duplicates.

        Returns:
            Unvalidated statuses.
        """
        ...


class ArtistLibrary(ArtistLookup, Protocol):
    """Observe artist catalog and live membership facts."""

    async def releases(self, identifier: str) -> list[str]:
        """Read primary-credit releases.

        Args:
            identifier: Artist identity.

        Returns:
            Unique release identities.
        """
        ...

    async def tracks(self, identifier: str, releases: list[str]) -> list[str]:
        """Read primary-credit tracks.

        Args:
            identifier: Artist identity.
            releases: Ordered release identities.

        Returns:
            Unique track identities.
        """
        ...

    @property
    def saved(self) -> LookupMembership:
        """Access saved-album observations.

        Returns:
            Live membership reader.
        """
        ...

    @property
    def liked(self) -> LookupMembership:
        """Access liked-track observations.

        Returns:
            Live membership reader.
        """
        ...
