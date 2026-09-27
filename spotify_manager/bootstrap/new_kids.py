"""Compose ordinary discovery review decisions with caller-owned integrations."""

from collections.abc import Callable
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.composer_routes import ReleaseChoiceReader
from spotify_manager.application.discovery_observations import DiscoveryObservations
from spotify_manager.application.new_kids_planner import NewKidsPlanner
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryAudit
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryCatalog
from spotify_manager.interfaces.presenters.new_kids import NewKidsPresenter


def review_planner(
    client: Spotify,
    retry: RetryCall,
    choose: ReleaseChoiceReader,
    *,
    year: int,
    dry_run: bool,
    history: AnnualScrobbleIndex,
    release_limit: int,
    studio_minimum: int,
    log_path: Path,
    echo: Callable[[str], None],
    catalogs: dict[str, tuple[RankedRelease, ...]],
    tracks: dict[str, tuple[CatalogTrack, ...]],
    liked: dict[str, bool],
    works: dict[str, tuple[PlaylistTrack, ...]],
) -> NewKidsPlanner:
    """Bind the original shared caches and effect boundaries to the release planner.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry/cancellation callback.
        choose: Existing release-choice callback.
        year: Original active year.
        dry_run: Whether planned results describe a preview.
        history: Current-year normalized listening observations.
        release_limit: Original studio preference and completion count.
        studio_minimum: Original studio distinct-title completion minimum.
        log_path: Existing routine audit destination.
        echo: Existing CLI or job message sink.
        catalogs: Shared accepted artist catalog cache.
        tracks: Shared accepted catalog-track cache.
        liked: Shared accepted live memberships.
        works: Shared accepted works-playlist cache.

    Returns:
        Planner over the existing invocation-owned observations and callbacks.
    """
    access = LegacyDiscoveryCatalog(client, retry)
    observations = DiscoveryObservations(
        access, history, release_limit, studio_minimum, catalogs, tracks, liked, works
    )
    return NewKidsPlanner(
        observations,
        choose,
        LegacyDiscoveryAudit(log_path),
        NewKidsPresenter(echo),
        year,
        dry_run,
    )
