"""Inject observed cache authorities without replacing filesystem implementations."""

from functools import partial
from typing import cast

from spotipy import Spotify

from spotify_manager.application.lookup_effects import CachedTracks
from spotify_manager.bootstrap.library_lookups import CacheRead
from spotify_manager.bootstrap.library_lookups import CacheWrite
from spotify_manager.bootstrap.library_lookups import ClientFactory
from spotify_manager.bootstrap.library_lookups import fetch_tracks
from spotify_manager.processors import library_lookups


def observed_cached_tracks(
    sp: Spotify | None, factory: ClientFactory | None
) -> CachedTracks:
    """Supply fixture-owned cache callbacks and the concrete delayed SDK reader.

    Args:
        sp: Original explicit client, if supplied.
        factory: Original delayed client factory.

    Returns:
        Original cache observations without changing file-helper behavior tests.
    """
    return CachedTracks(
        cast(CacheRead, library_lookups.load_album_tracks_cache),
        cast(CacheWrite, library_lookups.save_album_tracks_cache),
        partial(fetch_tracks, sp, factory),
    )
