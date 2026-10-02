"""Bind original lookup and lazy cache/client seams to application workflows."""

from collections.abc import Callable
from functools import partial
from typing import cast

from spotipy import Spotify

from spotify_manager.application.library_lookup_run import ArtistStatistics
from spotify_manager.application.lookup_effects import AlbumLookup
from spotify_manager.application.lookup_effects import ArtistLookup
from spotify_manager.application.lookup_effects import CachedTracks
from spotify_manager.application.lookup_effects import LocalAlbumLookup
from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.domain.lookup_values import TracklistUnavailableError


type ClientFactory = Callable[[], Spotify]
type CacheRead = Callable[[], dict[str, list[LookupTrack]]]
type CacheWrite = Callable[[dict[str, list[LookupTrack]]], None]


def artist_statistics(
    sp: Spotify, name: str | None, identifier: str | None
) -> ArtistStatistics:
    """Bind original ordered identity, catalog and live membership stages.

    Args:
        sp: Original caller-owned synchronous client.
        name: Original optional name.
        identifier: Original direct identity.

    Returns:
        Original explicitly constructed artist lookup dependencies.
    """
    from spotify_manager.processors import library_lookups as legacy

    return ArtistStatistics(
        partial(legacy.resolve_live_artist, sp, name=name, artist_id=identifier),
        partial(legacy._live_artist_release_ids, sp),
        partial(
            legacy._count_live_contains,
            contains=partial(legacy._saved_artist_statuses, sp),
            resource="Saved Albums",
        ),
        partial(legacy._live_primary_track_ids, sp),
        partial(
            legacy._count_live_contains,
            contains=partial(legacy._liked_artist_statuses, sp),
            resource="Liked Songs",
        ),
    )


def cached_tracks(sp: Spotify | None, factory: ClientFactory | None) -> CachedTracks:
    """Retain original delayed client selection after cache-hit checks.

    Args:
        sp: Original explicit client or none.
        factory: Original optional lazy client factory.

    Returns:
        Original cache authority and delayed read boundary.
    """
    from spotify_manager.processors import library_lookups as legacy

    return CachedTracks(
        cast(CacheRead, legacy.load_album_tracks_cache),
        cast(CacheWrite, legacy.save_album_tracks_cache),
        partial(fetch_tracks, sp, factory),
    )


def fetch_tracks(
    sp: Spotify | None, factory: ClientFactory | None, identifier: str
) -> list[LookupTrack]:
    """Select the original explicit client before truthy lazy factory invocation.

    Args:
        sp: Original explicit client or none.
        factory: Original optional lazy factory.
        identifier: Original requested identity.

    Returns:
        Original complete minimized track list.

    Raises:
        TracklistUnavailableError: No original client can be selected.
    """
    from spotify_manager.processors import library_lookups as legacy

    selected = sp if sp is not None else (factory() if factory else None)
    if selected is None:
        raise TracklistUnavailableError(
            f"Album {identifier!r} is not cached and no Spotify client is available."
        )
    return legacy._fetch_album_tracks(selected, identifier)


def local_album(
    sp: Spotify | None,
    factory: ClientFactory | None,
    use_cache: bool,
    refresh_cache: bool,
) -> LocalAlbumLookup:
    """Bind original local export and public track-cache stage.

    Args:
        sp: Original explicit client or none.
        factory: Original optional lazy factory.
        use_cache: Original cache authority flag.
        refresh_cache: Original cache-hit bypass flag.

    Returns:
        Original explicit local evaluation dependencies.
    """
    from spotify_manager.processors import library_lookups as legacy

    return LocalAlbumLookup(
        legacy.load_your_library_file,
        partial(
            legacy.get_album_tracklist,
            sp=sp,
            client_factory=factory,
            use_cache=use_cache,
            refresh_cache=refresh_cache,
        ),
    )


def artist_lookup(client: Spotify) -> ArtistLookup:
    """Bind original direct and search artist observation seams.

    Args:
        client: Original caller-owned synchronous client.

    Returns:
        Original identity reads without constructing an environment client.
    """
    from spotify_manager.processors import library_lookups as legacy

    return ArtistLookup(
        partial(legacy._direct_artist_identity, client),
        partial(_artist_candidates, client),
    )


def _artist_candidates(client: Spotify, name: str) -> list[tuple[str, str]]:
    from spotify_manager.infrastructure import lookup_records
    from spotify_manager.processors import library_lookups as legacy

    return lookup_records.artist_identities(legacy._artist_search_items(client, name))


def album_lookup(client: Spotify) -> AlbumLookup:
    """Bind original direct and search album observation seams.

    Args:
        client: Original caller-owned synchronous client.

    Returns:
        Original album reads without constructing an environment client.
    """
    from spotify_manager.processors import library_lookups as legacy

    return AlbumLookup(
        partial(legacy._direct_album, client), partial(legacy._album_search, client)
    )
