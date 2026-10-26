"""Named catalog, cache and membership resources for synchronous lookups."""

from dataclasses import dataclass
from typing import Protocol
from typing import cast

from spotipy import Spotify

from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.lookup_values import TracklistUnavailableError
from spotify_manager.infrastructure import lookup_records
from spotify_manager.models.your_library import YourLibraryFile


class ClientFactory(Protocol):
    """Acquire the caller-owned client only after a cache miss."""

    def client(self) -> Spotify:
        """Acquire the original synchronous client lazily.

        Returns:
            Original caller-owned client.
        """
        ...


@dataclass(frozen=True)
class SpotifyArtistLookup:
    """Read artist facts with one caller-owned client.

    Args:
        client: Synchronous Spotify client.
    """

    client: Spotify

    def direct(self, identifier: str) -> tuple[str, str] | None:
        """Read direct artist metadata.

        Args:
            identifier: Artist identity.

        Returns:
            Complete identity, or none for incomplete metadata.
        """
        from spotify_manager.processors.library_lookups import _direct_artist_identity

        return _direct_artist_identity(self.client, identifier)

    def search(self, name: str) -> list[tuple[str, str]]:
        """Read artist search candidates.

        Args:
            name: Exact reference.

        Returns:
            Ordered candidates.
        """
        from spotify_manager.processors.library_lookups import _artist_search_items

        return lookup_records.artist_identities(_artist_search_items(self.client, name))

    def releases(self, identifier: str) -> list[str]:
        """Read unique primary-credit releases.

        Args:
            identifier: Artist identity.

        Returns:
            Ordered release identities.
        """
        from spotify_manager.processors.library_lookups import _live_artist_release_ids

        return _live_artist_release_ids(self.client, identifier)

    def tracks(self, identifier: str, releases: list[str]) -> list[str]:
        """Read unique primary-credit tracks.

        Args:
            identifier: Artist identity.
            releases: Ordered release identities.

        Returns:
            Ordered track identities.
        """
        from spotify_manager.processors.library_lookups import _live_primary_track_ids

        return _live_primary_track_ids(self.client, identifier, releases)

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

    def direct(self, identifier: str) -> LiveAlbumCandidate:
        """Read direct album metadata.

        Args:
            identifier: Album identity.

        Returns:
            Album candidate.
        """
        from spotify_manager.processors.library_lookups import _direct_album

        return _direct_album(self.client, identifier)

    def search(self, name: str, artist: str | None) -> list[LiveAlbumCandidate]:
        """Read album search candidates.

        Args:
            name: Exact title.
            artist: Optional primary artist.

        Returns:
            Ordered candidates.
        """
        from spotify_manager.processors.library_lookups import _album_search

        return _album_search(self.client, name, artist)


@dataclass(frozen=True)
class SpotifyTrackLookup:
    """Read track facts with one caller-owned client.

    Args:
        client: Synchronous Spotify client.
    """

    client: Spotify

    def direct(self, identifier: str) -> ResolvedTrack:
        """Read direct track metadata.

        Args:
            identifier: Track identity.

        Returns:
            Track metadata.
        """
        from spotify_manager.processors.scrobble_lookups import _direct_track

        return _direct_track(self.client, identifier)

    def search(self, name: str) -> list[ResolvedTrack]:
        """Read track search candidates.

        Args:
            name: Exact title.

        Returns:
            Ordered candidates.
        """
        from spotify_manager.processors.scrobble_lookups import _track_search

        return lookup_records.track_identities(_track_search(self.client, name))


@dataclass(frozen=True)
class SavedArtistAlbums:
    """Read artist saved-release membership.

    Args:
        client: Caller-owned client.
    """

    client: Spotify

    def contains(self, identifiers: list[str]) -> object:
        """Observe a complete ordered batch.

        Args:
            identifiers: Requested identities.

        Returns:
            Unvalidated statuses.
        """
        from spotify_manager.processors.library_lookups import _saved_artist_statuses

        return _saved_artist_statuses(self.client, identifiers)


@dataclass(frozen=True)
class LikedArtistTracks:
    """Read artist liked-track membership.

    Args:
        client: Caller-owned client.
    """

    client: Spotify

    def contains(self, identifiers: list[str]) -> object:
        """Observe a complete ordered batch.

        Args:
            identifiers: Requested identities.

        Returns:
            Unvalidated statuses.
        """
        from spotify_manager.processors.library_lookups import _liked_artist_statuses

        return _liked_artist_statuses(self.client, identifiers)


@dataclass(frozen=True)
class LiveLikedTracks:
    """Read album-instrument liked-track membership.

    Args:
        client: Caller-owned client.
    """

    client: Spotify

    def contains(self, identifiers: list[str]) -> object:
        """Observe a complete ordered batch.

        Args:
            identifiers: Requested identities.

        Returns:
            Unvalidated statuses.
        """
        from spotify_manager.processors.library_lookups import _live_liked_statuses

        return _live_liked_statuses(self.client, identifiers)


@dataclass(frozen=True)
class AlbumTrackCache:
    """Own cache storage and delayed client acquisition.

    Args:
        client: Optional caller-owned client.
        factory: Retained public lazy-client compatibility hook.
    """

    client: Spotify | None
    factory: ClientFactory | None = None

    def load(self) -> dict[str, list[LookupTrack]]:
        """Read unchecked cache authority.

        Returns:
            Complete stored cache.
        """
        from spotify_manager.loaders_savers import load_album_tracks_cache

        return cast(dict[str, list[LookupTrack]], load_album_tracks_cache())

    def save(self, cache: dict[str, list[LookupTrack]]) -> None:
        """Publish the complete cache.

        Args:
            cache: Accepted cache.
        """
        from spotify_manager.loaders_savers import save_album_tracks_cache

        save_album_tracks_cache(cast(dict[str, list[dict[str, object]]], cache))

    def fetch(self, identifier: str) -> list[LookupTrack]:
        """Acquire a client after a cache miss, then read complete tracks.

        Args:
            identifier: Requested album.

        Returns:
            Complete minimized tracks.

        Raises:
            TracklistUnavailableError: No client is available.
        """
        from spotify_manager.processors.library_lookups import _fetch_album_tracks

        selected = self.client
        if selected is None and self.factory:
            selected = self.factory.client()
        if selected is None:
            raise TracklistUnavailableError(
                f"Album {identifier!r} is not cached "
                "and no Spotify client is available."
            )
        return _fetch_album_tracks(selected, identifier)


class LocalLibraryFiles:
    """Read the local export without choosing application stages."""

    def library(self) -> YourLibraryFile:
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

    def next_object(self, page: object) -> object:
        """Read object continuation.

        Args:
            page: Previous response.

        Returns:
            Next response.
        """
        from spotify_manager.processors.library_lookups import _next_object_page

        return _next_object_page(self.client, page)

    def release_page(self, artist: str, offset: int) -> object:
        """Read primary-credit release candidates.

        Args:
            artist: Primary identity.
            offset: Raw row offset.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.processors.library_lookups import _artist_release_page

        return _artist_release_page(self.client, artist, offset)

    def albums(self, identifiers: list[str]) -> object:
        """Read an album batch.

        Args:
            identifiers: Ordered identities.

        Returns:
            Unvalidated response.
        """
        from spotify_manager.processors.library_lookups import _album_batch

        return _album_batch(self.client, identifiers)

    def next_tracks(self, page: object) -> object:
        """Read embedded album-track continuation.

        Args:
            page: Previous response.

        Returns:
            Next response.
        """
        from spotify_manager.processors.library_lookups import _next_album_track_page

        return _next_album_track_page(self.client, page)
