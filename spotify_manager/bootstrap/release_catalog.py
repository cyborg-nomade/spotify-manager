"""Bind future-record observation to the original synchronous album-track seam."""

from spotify_manager.application.future_release import (
    matching_future_record as match_future,
)
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from spotify_manager.infrastructure.legacy.release_tracks import LegacyReleaseTracks
from spotify_manager.routines import release_check as legacy


async def matching_future_record(
    sp: Spotify,
    single: ReleaseTrack,
    future: tuple[ReleaseCandidate, ...],
    retry: legacy.RetryCall,
    cache: dict[str, tuple[ReleaseTrack, ...]] | None,
) -> ReleaseCandidate | None:
    """Retain original retries, ordered observations and mutable cache ownership.

    Args:
        sp: Caller-owned Spotify client.
        single: Original selected marker.
        future: Original ordered announced editions.
        retry: Original catalog retry policy.
        cache: Optional caller-owned track cache.

    Returns:
        First original matching record or no match.

    Raises:
        ReleaseCheckSpotifyError: Original track observation is unusable.
    """
    return await match_future(LegacyReleaseTracks(sp, retry), single, future, cache)
