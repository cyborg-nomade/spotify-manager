"""Construct named catalog and storage resources for library lookups."""

from spotify_manager.application.library_lookup_run import ArtistStatistics
from spotify_manager.application.lookup_effects import LocalAlbumLookup
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.infrastructure.lookup_resources import AlbumTrackCache
from spotify_manager.infrastructure.lookup_resources import LocalLibraryFiles
from spotify_manager.infrastructure.lookup_resources import (
    NativeClientFactory as ClientFactory,
)
from spotify_manager.infrastructure.lookup_resources import SpotifyAlbumLookup
from spotify_manager.infrastructure.lookup_resources import SpotifyArtistLookup


def artist_statistics(
    sp: Spotify, name: str | None, identifier: str | None
) -> ArtistStatistics:
    """Construct live artist observations.

    Args:
        sp: Caller-owned client.
        name: Optional exact name.
        identifier: Preferred direct identity.

    Returns:
        Typed lookup request and catalog.
    """
    from spotify_manager.processors.library_lookups import SPOTIFY_CONTAINS_BATCH_SIZE

    return ArtistStatistics(
        SpotifyArtistLookup(sp), name, identifier, SPOTIFY_CONTAINS_BATCH_SIZE
    )


def cached_tracks(sp: Spotify | None, factory: ClientFactory | None) -> AlbumTrackCache:
    """Construct cache storage with delayed client acquisition.

    Args:
        sp: Optional explicit client.
        factory: Public lazy-client compatibility hook.

    Returns:
        Named cache resource.
    """
    return AlbumTrackCache(sp, factory)


def local_album(
    sp: Spotify | None,
    factory: ClientFactory | None,
    use_cache: bool,
    refresh_cache: bool,
) -> LocalAlbumLookup:
    """Construct export and cache resources without concealing tracklist execution.

    Args:
        sp: Optional explicit client.
        factory: Public lazy-client compatibility hook.
        use_cache: Enable cache reads and publication.
        refresh_cache: Bypass cache hits.

    Returns:
        Cohesive local evaluation dependencies.
    """
    return LocalAlbumLookup(
        LocalLibraryFiles(), cached_tracks(sp, factory), use_cache, refresh_cache
    )


def artist_lookup(client: Spotify) -> SpotifyArtistLookup:
    """Construct direct and search artist observations.

    Args:
        client: Caller-owned client.

    Returns:
        Named artist catalog.
    """
    return SpotifyArtistLookup(client)


def album_lookup(client: Spotify) -> SpotifyAlbumLookup:
    """Construct direct and search album observations.

    Args:
        client: Caller-owned client.

    Returns:
        Named album catalog.
    """
    return SpotifyAlbumLookup(client)
