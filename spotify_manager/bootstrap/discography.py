"""Compose original synchronous Discography facades with typed application owners."""

from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.discography_execution import DiscographyEffects
from spotify_manager.application.discography_execution import DiscographyExecution
from spotify_manager.application.discography_execution import DiscographyStateAccess
from spotify_manager.application.discography_history import resolve_historical
from spotify_manager.application.discography_planning import DiscographyPlanning
from spotify_manager.application.discography_planning import DiscographyReads
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.infrastructure.discography_observations import catalog
from spotify_manager.infrastructure.discography_observations import historical
from spotify_manager.infrastructure.discography_observations import queues
from spotify_manager.routines import discography as legacy


def _direct(operation: Callable[[], object], description: str) -> object:
    return operation()


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _priority(path: Path, service: StateService | None) -> dict[str, object]:
    from spotify_manager.routines.discography import _state_access

    return _state_access(path, service).load()


def _state(path: Path, service: StateService | None) -> DiscographyStateAccess:
    from spotify_manager.routines.discography import _state_access

    return _state_access(path, service)


def _catalog(
    spotify: Spotify, retry: legacy.RetryCall, candidate: QueueArtist
) -> tuple[CatalogRelease, ...]:
    return catalog(spotify, candidate.spotify_id, retry)


def _resolve(
    spotify: Spotify,
    choice: legacy.HistoricalArtistChoiceReader | None,
    retry: legacy.RetryCall,
    selection: HistoricalArtistSelection,
) -> QueueArtist:
    return resolve_historical(selection, partial(_artist, spotify, choice, retry))


def _artist(
    spotify: Spotify,
    choice: legacy.HistoricalArtistChoiceReader | None,
    retry: legacy.RetryCall,
    name: str,
) -> SpotifyArtistCandidate | None:
    from spotify_manager.routines.something_old import resolve_spotify_artist

    return resolve_spotify_artist(spotify, name, choice, retry)


def resolve_artist(
    spotify: Spotify,
    selection: HistoricalArtistSelection,
    choice: legacy.HistoricalArtistChoiceReader | None,
    retry: legacy.RetryCall,
) -> QueueArtist:
    """Bind original exact artist mapping with caller interaction and retry seams.

    Args:
        spotify: Original SDK client.
        selection: Original complete historical selection.
        choice: Original optional mapping interaction.
        retry: Original caller retry.

    Returns:
        Original resolved historical candidate.
    """
    return resolve_historical(selection, partial(_artist, spotify, choice, retry))


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
    caller_retry = retry or _direct
    reads = DiscographyReads(
        partial(_priority, state_path, service),
        partial(queues, spotify, playlists, caller_retry, extra),
        partial(
            historical,
            history_path,
            today,
            random,
            progress,
        ),
        partial(_resolve, spotify, choice, caller_retry),
        partial(_catalog, spotify, caller_retry),
        selector,
        partial(_progress, progress),
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
    from spotify_manager.routines.discography import _append_log
    from spotify_manager.routines.discography import _remove_batch

    caller_retry = retry or _direct
    effects = DiscographyEffects(
        partial(_remove_batch, spotify, caller_retry),
        partial(_append_log, path=audit_path),
        partial(_state, state_path, service),
        partial(_progress, progress),
    )
    return DiscographyExecution(effects, legacy.PLAYLIST_MUTATION_BATCH_SIZE)
