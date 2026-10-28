"""Named catalog, cache and membership resources for synchronous lookups."""

import asyncio
from dataclasses import dataclass
from typing import Protocol
from typing import cast

from spotipy import Spotify as LegacySpotify

from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.lookup_values import TracklistUnavailableError
from spotify_manager.infrastructure import lookup_records
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.models.your_library import YourLibraryFile


class ClientFactory(Protocol):
    """Acquire the caller-owned client only after a cache miss."""

    def client(self) -> LegacySpotify:
        """Acquire the original synchronous client lazily.

        Returns:
            Original caller-owned client.
        """
        ...


class NativeClientFactory(Protocol):
    """Acquire an already adapted client after a cache miss."""

    def client(self) -> Spotify:
        """Acquire the client at the original lazy observation boundary.

        Returns:
            Native or compatibility client owned by the caller.
        """
        ...


@dataclass(frozen=True)
class SpotifyArtistLookup:
    """Read artist facts with one caller-owned client.

    Args:
        client: Synchronous Spotify client.
    """

    client: Spotify

    async def direct(self, identifier: str) -> tuple[str, str] | None:
        """Read direct artist metadata.

        Args:
            identifier: Artist identity.

        Returns:
            Complete identity, or none for incomplete metadata.
        """
        from spotify_manager.processors.library_lookups import _direct_artist_identity

        return await _direct_artist_identity(self.client, identifier)

    async def search(self, name: str) -> list[tuple[str, str]]:
        """Read artist search candidates.

        Args:
            name: Exact reference.

        Returns:
            Ordered candidates.
        """
        from spotify_manager.processors.library_lookups import _artist_search_items

        return lookup_records.artist_identities(
            await _artist_search_items(self.client, name)
        )

    async def releases(self, identifier: str) -> list[str]:
        """Read unique primary-credit releases.

        Args:
            identifier: Artist identity.

        Returns:
            Ordered release identities.
        """
        from spotify_manager.processors.library_lookups import _live_artist_release_ids

        return await _live_artist_release_ids(self.client, identifier)

    async def tracks(self, identifier: str, releases: list[str]) -> list[str]:
        """Read unique primary-credit tracks.

        Args:
            identifier: Artist identity.
            releases: Ordered release identities.

        Returns:
            Ordered track identities.
        """
        from spotify_manager.processors.library_lookups import _live_primary_track_ids

        return await _live_primary_track_ids(self.client, identifier, releases)

    @property
    def saved(self) -> SavedArtistAlbums:
        """Access live saved-album facts.

        Returns:
            Named membership resource.
        """
        return SavedArtistAlbums(self.client)

    @property
    def liked(self) -> LikedArtistTracks:
        """Access live liked-track facts.

        Returns:
            Named membership resource.
        """
        return LikedArtistTracks(self.client)


@dataclass(frozen=True)
class SpotifyAlbumLookup:
    """Read album facts with one caller-owned client.

    Args:
        client: Synchronous Spotify client.
    """

    client: Spotify

    async def direct(self, identifier: str) -> LiveAlbumCandidate:
        """Read direct album metadata.

        Args:
            identifier: Album identity.

        Returns:
            Album candidate.
        """
        from spotify_manager.processors.library_lookups import _direct_album

        return await _direct_album(self.client, identifier)

    async def search(self, name: str, artist: str | None) -> list[LiveAlbumCandidate]:
        """Read album search candidates.

        Args:
            name: Exact title.
            artist: Optional primary artist.

        Returns:
            Ordered candidates.
        """
        from spotify_manager.processors.library_lookups import _album_search

        return await _album_search(self.client, name, artist)


@dataclass(frozen=True)
class SpotifyTrackLookup:
    """Read track facts with one caller-owned client.

    Args:
        client: Synchronous Spotify client.
    """

    client: Spotify

    async def direct(self, identifier: str) -> ResolvedTrack:
        """Read direct track metadata.

        Args:
            identifier: Track identity.

        Returns:
            Track metadata.
        """
        from spotify_manager.processors.scrobble_lookups import _direct_track

        return await _direct_track(self.client, identifier)

    async def search(self, name: str) -> list[ResolvedTrack]:
        """Read track search candidates.

        Args:
            name: Exact title.

        Returns:
            Ordered candidates.
        """
        from spotify_manager.processors.scrobble_lookups import _track_search

        return lookup_records.track_identities(await _track_search(self.client, name))


@dataclass(frozen=True)
class SavedArtistAlbums:
    """Read artist saved-release membership.

    Args:
        client: Caller-owned client.
    """

    client: Spotify

    async def contains(self, identifiers: list[str]) -> object:
        """Observe a complete ordered batch.

        Args:
            identifiers: Requested identities.

        Returns:
            Unvalidated statuses.
        """
        from spotify_manager.processors.library_lookups import _saved_artist_statuses

        return await _saved_artist_statuses(self.client, identifiers)


@dataclass(frozen=True)
class LikedArtistTracks:
    """Read artist liked-track membership.

    Args:
        client: Caller-owned client.
    """

    client: Spotify

    async def contains(self, identifiers: list[str]) -> object:
        """Observe a complete ordered batch.

        Args:
            identifiers: Requested identities.

        Returns:
            Unvalidated statuses.
        """
        from spotify_manager.processors.library_lookups import _liked_artist_statuses

        return await _liked_artist_statuses(self.client, identifiers)


@dataclass(frozen=True)
class LiveLikedTracks:
    """Read album-instrument liked-track membership.

    Args:
        client: Caller-owned client.
    """

    client: Spotify

    async def contains(self, identifiers: list[str]) -> object:
        """Observe a complete ordered batch.

        Args:
            identifiers: Requested identities.

        Returns:
            Unvalidated statuses.
        """
        from spotify_manager.processors.library_lookups import _live_liked_statuses

        return await _live_liked_statuses(self.client, identifiers)


@dataclass(frozen=True)
class AlbumTrackCache:
    """Own cache storage and delayed client acquisition.

    Args:
        client: Optional caller-owned client.
        factory: Retained public lazy-client compatibility hook.
    """

    client: Spotify | None
    factory: NativeClientFactory | None = None

    async def load(self) -> dict[str, list[LookupTrack]]:
        """Read unchecked cache authority.

        Returns:
            Complete stored cache.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_load))
            return await finish_blocking(task)

    def _blocking_load(self) -> dict[str, list[LookupTrack]]:
        """Read unchecked cache authority.

        Returns:
            Complete stored cache.
        """
        from spotify_manager.loaders_savers import load_album_tracks_cache

        return cast(dict[str, list[LookupTrack]], load_album_tracks_cache())

    async def save(self, cache: dict[str, list[LookupTrack]]) -> None:
        """Publish the complete cache.

        Args:
            cache: Accepted cache.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_save, cache))
            return await finish_blocking(task)

    def _blocking_save(self, cache: dict[str, list[LookupTrack]]) -> None:
        """Publish the complete cache.

        Args:
            cache: Accepted cache.
        """
        from spotify_manager.loaders_savers import save_album_tracks_cache

        save_album_tracks_cache(cast(dict[str, list[dict[str, object]]], cache))

    async def fetch(self, identifier: str) -> list[LookupTrack]:
        """Acquire a client after a cache miss, then read complete tracks.

        Args:
            identifier: Requested album.

        Returns:
            Complete minimized tracks.

        Raises:
            TracklistUnavailableError: No client is available.
        """
        from spotify_manager.processors.library_lookups import _async_fetch_album_tracks

        selected = self.client
        if selected is None and self.factory:
            selected = self.factory.client()
        if selected is None:
            raise TracklistUnavailableError(
                f"Album {identifier!r} is not cached "
                "and no Spotify client is available."
            )
        return await _async_fetch_album_tracks(selected, identifier)


class LocalLibraryFiles:
    """Read the local export without choosing application stages."""

    async def library(self) -> YourLibraryFile:
        """Read the export authority.

        Returns:
            Complete validated library.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self._blocking_library))
            return await finish_blocking(task)

    def _blocking_library(self) -> YourLibraryFile:
        """Read the export authority.

        Returns:
            Complete validated library.
        """
        from spotify_manager.loaders_savers import load_your_library_file

        return load_your_library_file()


@dataclass(frozen=True)
class SpotifyLookupPages:
    """Read lookup catalog pages with one caller-owned client.

    Args:
        client: Synchronous Spotify client.
    """

    client: Spotify

    async def next_object(self, page: object) -> object:
        """Read object continuation.

        Args:
            page: Previous response.

        Returns:
            Next response.
        """
        from spotify_manager.processors.library_lookups import _next_object_page

        return await _next_object_page(self.client, page)

    async def release_page(self, artist: str, offset: int) -> object:
        """Read primary-credit release candidates.

        Args:
            artist: Primary identity.
            offset: Raw row offset.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.processors.library_lookups import _artist_release_page

        return await _artist_release_page(self.client, artist, offset)

    async def albums(self, identifiers: list[str]) -> object:
        """Read an album batch.

        Args:
            identifiers: Ordered identities.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.processors.library_lookups import _album_batch

        return await _album_batch(self.client, identifiers)

    async def next_tracks(self, page: object) -> object:
        """Read embedded album-track continuation.

        Args:
            page: Previous response.

        Returns:
            Next response.
        """
        from spotify_manager.processors.library_lookups import _next_album_track_page

        return await _next_album_track_page(self.client, page)
