"""Bind future-record observation to the original synchronous album-track seam."""

from functools import partial

from spotipy import Spotify

from spotify_manager.application.future_release import (
    matching_future_record as match_future,
)
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from spotify_manager.routines import release_check as legacy


def _tracks(
    sp: Spotify, retry: legacy.RetryCall, release: ReleaseCandidate
) -> tuple[ReleaseTrack, ...]:
    return legacy.load_release_tracks(sp, release, retry)


def matching_future_record(
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
    return match_future(partial(_tracks, sp, retry), single, future, cache)
