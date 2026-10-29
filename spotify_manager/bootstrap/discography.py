"""Compose original synchronous Discography facades with typed application owners."""

from datetime import date
from pathlib import Path

from spotify_manager.application.discography_catalog import DiscographyCatalog
from spotify_manager.application.discography_execution import DiscographyExecution
from spotify_manager.application.discography_history import DiscographyArtistMapping
from spotify_manager.application.discography_history import DiscographyHistory
from spotify_manager.application.discography_planning import DiscographyPlanning
from spotify_manager.application.discography_planning import DiscographyReads
from spotify_manager.application.discography_queues import DiscographyQueues
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.discography_values import QueueName
from spotify_manager.infrastructure.discography_observations import (
    DiscographyArtistCatalog,
)
from spotify_manager.infrastructure.discography_observations import DiscographyPriority
from spotify_manager.infrastructure.discography_observations import DiscographySpotify
from spotify_manager.infrastructure.discography_observations import DiscographyWrites
from spotify_manager.infrastructure.legacy.dated_history import LegacyDatedHistory
from spotify_manager.routines import discography as legacy


def history_stage(
    path: Path,
    today: date | None,
    random: legacy.RandomIndexReader,
    progress: legacy.ProgressCallback | None,
) -> DiscographyHistory:
    """Build the named historical-selection stage without reading inputs.

    Args:
        path: Original history export.
        today: Optional effective date.
        random: Original external random reader.
        progress: Optional stage notification.

    Returns:
        Configured historical-selection application stage.
    """
    return DiscographyHistory(
        LegacyDatedHistory(path, today, random),
        OptionalMessages(progress),
        legacy.blast_from_past.FIRST_ELIGIBLE_DATE,
    )


def queue_stage(
    spotify: Spotify,
    playlists: dict[QueueName, str],
    retry: legacy.RetryCall,
    extra: str | None,
) -> DiscographyQueues:
    """Build the named source-gathering stage without reading playlists.

    Args:
        spotify: Caller-owned client.
        playlists: Original source identities.
        retry: Original read retry policy.
        extra: Optional auxiliary marker source.

    Returns:
        Configured queue-gathering application stage.
    """
    return DiscographyQueues(DiscographySpotify(spotify, retry), playlists, extra)


def catalog_stage(spotify: Spotify, retry: legacy.RetryCall) -> DiscographyCatalog:
    """Build the named catalog-selection stage without reading Spotify.

    Args:
        spotify: Caller-owned client.
        retry: Original read retry policy.

    Returns:
        Configured catalog-selection application stage.
    """
    return DiscographyCatalog(
        DiscographySpotify(spotify, retry), legacy.SAVED_ALBUM_BATCH_SIZE
    )


def historical_mapping(
    spotify: Spotify,
    choice: legacy.HistoricalArtistChoiceReader | None,
    retry: legacy.RetryCall,
) -> DiscographyArtistMapping:
    """Build the named historical mapping stage without observing artists.

    Args:
        spotify: Caller-owned client.
        choice: Optional original ambiguity interaction.
        retry: Original read retry policy.

    Returns:
        Configured historical mapping application stage.
    """
    return DiscographyArtistMapping(DiscographyArtistCatalog(spotify, choice, retry))


def planning(
    spotify: Spotify,
    playlists: dict[QueueName, str],
    selector: legacy.ReleaseSelector,
    extra: str | None,
    choice: legacy.HistoricalArtistChoiceReader | None,
    history_path: Path,
    today: date | None,
    random: legacy.RandomIndexReader,
    retry: legacy.RetryCall | None,
    progress: legacy.ProgressCallback | None,
    state_path: Path,
    service: StateService | None,
) -> DiscographyPlanning:
    """Bind original preflight, lazy fallback, catalog and interaction seams.

    Args:
        spotify: Original caller-owned SDK client.
        playlists: Original source identities.
        selector: Original release choice interaction.
        extra: Original optional auxiliary marker source.
        choice: Original historical mapping interaction.
        history_path: Original history export.
        today: Original optional cutoff date override.
        random: Original index reader.
        retry: Original optional retry boundary.
        progress: Original optional progress presenter.
        state_path: Original priority location.
        service: Original optional shared service.

    Returns:
        Original complete synchronous planning use case.
    """
    caller_retry = retry or NoRetry()
    reads = DiscographyReads(
        DiscographyPriority(state_path, service),
        queue_stage(spotify, playlists, caller_retry, extra),
        history_stage(history_path, today, random, progress),
        historical_mapping(spotify, choice, caller_retry),
        catalog_stage(spotify, caller_retry),
        selector,
        OptionalMessages(progress),
    )
    return DiscographyPlanning(reads, legacy.WEEK_RELEASES)


def execution(
    spotify: Spotify,
    retry: legacy.RetryCall | None,
    progress: legacy.ProgressCallback | None,
    state_path: Path,
    service: StateService | None,
    audit_path: Path,
) -> DiscographyExecution:
    """Bind original mutation retry, artist audit and final checkpoint timing.

    Args:
        spotify: Original caller-owned SDK client.
        retry: Original optional retry boundary.
        progress: Original optional presenter.
        state_path: Original priority location.
        service: Original optional shared service.
        audit_path: Original completion audit file.

    Returns:
        Original complete synchronous execution use case.
    """
    caller_retry = retry or NoRetry()
    effects = DiscographyWrites(
        spotify, caller_retry, state_path, service, audit_path, progress
    )
    return DiscographyExecution(effects, legacy.PLAYLIST_MUTATION_BATCH_SIZE)
