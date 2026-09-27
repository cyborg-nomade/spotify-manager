"""Compose historical release completion for New Kids and Queue 2."""

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.release_history import played_releases
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex
from spotify_manager.infrastructure.legacy.release_history import LegacyReleaseHistory


def observe_played_releases(
    client: Spotify,
    catalog: tuple[RankedRelease, ...],
    history: AnnualScrobbleIndex,
    retry: RetryCall,
    track_cache: dict[str, tuple[CatalogTrack, ...]],
    liked_cache: dict[str, bool],
    *,
    release_limit: int,
    studio_minimum: int,
) -> tuple[RankedRelease, ...]:
    """Bind current history and the original SDK reads to the completion application.

    Args:
        client: Caller-owned synchronous Spotify client.
        catalog: Original ranked release observations.
        history: Current-year normalized evidence.
        retry: Existing retry/cancellation boundary.
        track_cache: Shared run-owned track observations.
        liked_cache: Shared run-owned membership observations.
        release_limit: Existing studio-release preference count.
        studio_minimum: Existing distinct-title threshold for studio completion.

    Returns:
        Completed entries in catalog order, retaining duplicates.
    """
    return played_releases(
        LegacyReleaseHistory(client, retry),
        catalog,
        history,
        track_cache,
        liked_cache,
        release_limit=release_limit,
        studio_minimum=studio_minimum,
    )
