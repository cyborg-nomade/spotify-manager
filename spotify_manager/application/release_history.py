"""Observe only releases with enough historical evidence to qualify for completion."""

from typing import Protocol

from spotify_manager.domain.completion import scrobble_threshold
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex
from spotify_manager.domain.discovery_history import release_was_played
from spotify_manager.domain.discovery_history import review_catalog
from spotify_manager.domain.discovery_history import scrobbled_titles


class ReleaseHistoryCatalog(Protocol):
    """Supply original track and membership reads without exposing the Spotify SDK."""

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Observe one release whose history passed the inexpensive prefilter.

        Args:
            release: Candidate release.

        Returns:
            Original ordered tracks with their primary credits.
        """

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Populate previously unseen live track memberships.

        Args:
            ids: Ordered track identifiers, retaining duplicates.
            cache: Shared run-owned liked-status cache, updated in place.
        """


def played_releases(
    access: ReleaseHistoryCatalog,
    catalog: tuple[RankedRelease, ...],
    history: AnnualScrobbleIndex,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
    liked_cache: dict[str, bool],
    *,
    release_limit: int = 4,
    studio_minimum: int = 3,
) -> tuple[RankedRelease, ...]:
    """Select completed releases while preserving observation order and shared caches.

    Args:
        access: Existing catalog and live-membership boundaries.
        catalog: Ranked catalog in original order, retaining duplicate entries.
        history: Current-year normalized listening evidence.
        track_cache: Shared accepted track observations, including empty responses.
        liked_cache: Shared accepted live memberships.
        release_limit: Existing studio-release preference count.
        studio_minimum: Existing distinct-title threshold for studio completion.

    Returns:
        Completed catalog entries in original order, retaining duplicates.
    """
    played = []
    for release in review_catalog(catalog, release_limit):
        titles = scrobbled_titles(history, release.identity)
        if len(titles) < scrobble_threshold(release.tier, studio_minimum):
            continue
        tracks = _observe(access, release, track_cache, liked_cache)
        if release_was_played(release, tracks, liked_cache, history, studio_minimum):
            played.append(release)
    return tuple(played)


def _observe(
    access: ReleaseHistoryCatalog,
    release: RankedRelease,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
    liked_cache: dict[str, bool],
) -> tuple[CatalogTrack, ...]:
    tracks = track_cache.get(release.spotify_id)
    if tracks is None:
        tracks = access.tracks(release)
        track_cache[release.spotify_id] = tracks
    access.likes([track.spotify_id for track in tracks], liked_cache)
    return tracks
