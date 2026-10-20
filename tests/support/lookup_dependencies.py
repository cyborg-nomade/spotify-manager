"""Observe retained cache compatibility seams through named methods."""

from typing import cast

from spotipy import Spotify

from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.infrastructure.lookup_resources import AlbumTrackCache
from spotify_manager.infrastructure.lookup_resources import ClientFactory
from spotify_manager.processors import library_lookups


class ObservedTrackCache(AlbumTrackCache):
    """Observe public cache reads and writes while using real track acquisition."""

    def load(self) -> dict[str, list[LookupTrack]]:
        """Read fixture cache authority.

        Returns:
            Original unchecked cache.
        """
        return cast(
            dict[str, list[LookupTrack]], library_lookups.load_album_tracks_cache()
        )

    def save(self, cache: dict[str, list[LookupTrack]]) -> None:
        """Accept fixture cache authority.

        Args:
            cache: Complete accepted cache.
        """
        library_lookups.save_album_tracks_cache(
            cast(dict[str, list[dict[str, object]]], cache)
        )


def observed_cached_tracks(
    sp: Spotify | None, factory: ClientFactory | None
) -> AlbumTrackCache:
    """Construct observed cache storage.

    Args:
        sp: Optional explicit client.
        factory: Public delayed client hook.

    Returns:
        Named cache owner.
    """
    return ObservedTrackCache(sp, factory)
