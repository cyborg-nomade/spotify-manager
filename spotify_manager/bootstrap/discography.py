"""Compose original synchronous Discography facades with typed application owners."""

from collections.abc import Callable
from datetime import date
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.discography_catalog import DiscographyCatalog
from spotify_manager.application.discography_catalog import DiscographyPage
from spotify_manager.application.discography_execution import DiscographyEffects
from spotify_manager.application.discography_execution import DiscographyExecution
from spotify_manager.application.discography_execution import DiscographyStateAccess
from spotify_manager.application.discography_history import DiscographyHistory
from spotify_manager.application.discography_history import resolve_historical
from spotify_manager.application.discography_planning import DiscographyPlanning
from spotify_manager.application.discography_planning import DiscographyReads
from spotify_manager.application.discography_queues import DiscographyQueues
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.infrastructure.discography_records import catalog_page
from spotify_manager.infrastructure.discography_records import saved_statuses
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import discography as legacy
from spotify_manager.routines import new_wine
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import something_old


def _direct(operation: Callable[[], object], description: str) -> object:
    return operation()


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _priority(path: Path, service: StateService | None) -> dict[str, object]:
    return legacy._state_access(path, service).load()


def _state(path: Path, service: StateService | None) -> DiscographyStateAccess:
    return legacy._state_access(path, service)


def _catalog(
    spotify: Spotify, retry: legacy.RetryCall, candidate: QueueArtist
) -> tuple[CatalogRelease, ...]:
    return legacy.load_release_catalog(spotify, candidate.spotify_id, retry)


def _resolve(
    spotify: Spotify,
    choice: legacy.HistoricalArtistChoiceReader | None,
    retry: legacy.RetryCall,
    selection: HistoricalArtistSelection,
) -> QueueArtist:
    return legacy.resolve_historical_artist(spotify, selection, choice, retry)


def _artist(
    spotify: Spotify,
    choice: legacy.HistoricalArtistChoiceReader | None,
    retry: legacy.RetryCall,
    name: str,
) -> SpotifyArtistCandidate | None:
    return something_old.resolve_spotify_artist(spotify, name, choice, retry)


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
        partial(legacy._load_artist_queues, spotify, playlists, caller_retry, extra),
        partial(
            legacy.select_historical_artist,
            path=history_path,
            today=today,
            random_index_reader=random,
            progress_callback=progress,
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
    caller_retry = retry or _direct
    effects = DiscographyEffects(
        partial(legacy._remove_batch, spotify, caller_retry),
        partial(legacy._append_log, path=audit_path),
        partial(_state, state_path, service),
        partial(_progress, progress),
    )
    return DiscographyExecution(effects, legacy.PLAYLIST_MUTATION_BATCH_SIZE)


def historical(
    path: Path,
    today: date | None,
    random: legacy.RandomIndexReader,
    progress: legacy.ProgressCallback | None,
) -> HistoricalArtistSelection:
    """Bind original history loading before calendar and random reads.

    Args:
        path: Original history export.
        today: Original optional effective date.
        random: Original caller index reader.
        progress: Original optional stage presenter.

    Returns:
        Complete original historical selection.
    """
    return DiscographyHistory(
        partial(blast_from_past.load_scrobbles_by_date, path),
        partial(palace_of_memory.palace_cutoff, today),
        random,
        partial(_progress, progress),
        blast_from_past.FIRST_ELIGIBLE_DATE,
    ).run()


def _playlist(
    spotify: Spotify, retry: legacy.RetryCall, playlist: str
) -> tuple[PlaylistTrack, ...]:
    try:
        return new_wine.load_playlist_tracks(spotify, playlist, retry)
    except new_wine.NewWineError as exc:
        raise DiscographyError(str(exc)) from exc


def queues(
    spotify: Spotify,
    playlists: dict[QueueName, str],
    retry: legacy.RetryCall,
    extra: str | None,
) -> tuple[
    dict[QueueName, tuple[QueueArtist, ...]], dict[str, tuple[ArtistMarkers, ...]]
]:
    """Bind original playlist observations without importing private routine policies.

    Args:
        spotify: Original SDK client.
        playlists: Original source identities.
        retry: Original caller retry.
        extra: Original optional auxiliary playlist.

    Returns:
        Original complete queues and marker groups.
    """
    return DiscographyQueues(partial(_playlist, spotify, retry), playlists, extra).run()


def _page(
    spotify: Spotify, artist: str, retry: legacy.RetryCall, offset: int
) -> DiscographyPage:
    return catalog_page(legacy._release_page(spotify, artist, offset, retry), artist)


def _saved(
    spotify: Spotify, retry: legacy.RetryCall, identities: list[str]
) -> list[bool]:
    raw = legacy._saved_batch(spotify, identities, retry)
    return saved_statuses(raw, len(identities))


def catalog(
    spotify: Spotify, artist: str, retry: legacy.RetryCall
) -> tuple[CatalogRelease, ...]:
    """Bind original raw pages and exact saved-status batch validation.

    Args:
        spotify: Original SDK client.
        artist: Original primary identity.
        retry: Original caller retry.

    Returns:
        Original canonical chronological catalog.
    """
    return DiscographyCatalog(
        partial(_page, spotify, artist, retry),
        partial(_saved, spotify, retry),
        legacy.SAVED_ALBUM_BATCH_SIZE,
    ).run()
