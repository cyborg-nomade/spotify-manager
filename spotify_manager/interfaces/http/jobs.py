"""Own HTTP job resources, dispatch and concrete integration wiring."""

import asyncio
import logging
import os
from collections.abc import AsyncIterator as AsyncIterator
from collections.abc import Iterator as Iterator
from contextlib import asynccontextmanager as asynccontextmanager
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta
from functools import lru_cache as lru_cache
from pathlib import Path as Path
from threading import Lock as Lock
from typing import Annotated as Annotated
from typing import Any as Any
from typing import Literal as Literal
from uuid import uuid4 as uuid4

from fastapi import Depends as Depends
from fastapi import FastAPI as FastAPI
from fastapi import HTTPException as HTTPException
from fastapi import Query as Query
from fastapi import Request as Request
from fastapi.responses import JSONResponse as JSONResponse
from fastapi.responses import Response as Response
from requests.exceptions import RequestException as RequestException
from spotipy.exceptions import SpotifyException as SpotifyException

from spotify_manager.application.job_lifecycle import (
    ACTIVE_STATUSES as _ACTIVE_JOB_STATUSES,
)
from spotify_manager.application.job_lifecycle import JobIdentity as JobIdentity
from spotify_manager.application.job_lifecycle import append_log as append_log
from spotify_manager.application.job_lifecycle import (
    first_active_job as first_active_job,
)
from spotify_manager.application.job_lifecycle import retain_logs as retain_logs
from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.execution import ExecutionRuntime
from spotify_manager.bootstrap.execution import current_execution
from spotify_manager.bootstrap.startup import (
    hydrate_library_data as hydrate_runtime_library_data,
)
from spotify_manager.client import get_spotipy_client as get_spotipy_client
from spotify_manager.client.lastfm import LastFmClient as LastFmClient
from spotify_manager.client.lastfm import LastFmError as LastFmError
from spotify_manager.core.library_data import LibraryDataError as LibraryDataError
from spotify_manager.core.library_data.runtime import (
    get_library_data_service as get_library_data_service,
)
from spotify_manager.core.state.definitions import StateDefinition
from spotify_manager.core.state.editor import state_editor_schema as state_editor_schema
from spotify_manager.core.state.editor import (
    validate_namespace_editor_change as validate_namespace_editor_change,
)
from spotify_manager.core.state.models import (
    StateConfigurationError as StateConfigurationError,
)
from spotify_manager.core.state.models import StateConflictError as StateConflictError
from spotify_manager.core.state.models import StateDocumentError as StateDocumentError
from spotify_manager.core.state.models import StateError as StateError
from spotify_manager.core.state.models import canonical_json as canonical_json
from spotify_manager.core.state.models import namespace_value as namespace_value
from spotify_manager.core.state.runtime import get_state_service as get_state_service
from spotify_manager.infrastructure.async_signal import AsyncSignal as Event
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.routine_state_codecs import DiscographyStateCodec
from spotify_manager.infrastructure.routine_state_codecs import GenreRevealStateCodec
from spotify_manager.infrastructure.routine_state_codecs import NewKidsStateCodec
from spotify_manager.infrastructure.routine_state_codecs import NewWineStateCodec
from spotify_manager.infrastructure.routine_state_codecs import NewYearStateDefinition
from spotify_manager.infrastructure.routine_state_codecs import PalaceOfMemoryStateCodec
from spotify_manager.infrastructure.routine_state_codecs import Queue3StateCodec
from spotify_manager.infrastructure.routine_state_codecs import (
    RecoverRemovedAlbumsStateCodec,
)
from spotify_manager.infrastructure.routine_state_codecs import ReleaseCheckStateCodec
from spotify_manager.infrastructure.routine_state_codecs import (
    ReviewAlbumLimitsStateCodec,
)
from spotify_manager.infrastructure.routine_state_codecs import ReviewArtistsStateCodec
from spotify_manager.infrastructure.routine_state_codecs import SlowListeningStateCodec
from spotify_manager.infrastructure.routine_state_codecs import TheQueueStateCodec
from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.interfaces import sauvignon_operations as sauvignon
from spotify_manager.interfaces.http.analysis_context import AnalysisContext
from spotify_manager.interfaces.http.analysis_worker import (
    AnalysisWorker as AnalysisWorker,
)
from spotify_manager.interfaces.http.job_queries import (
    active_analysis_snapshots as active_analysis_snapshots,
)
from spotify_manager.interfaces.http.job_queries import (
    active_playlist_snapshots as active_playlist_snapshots,
)
from spotify_manager.interfaces.http.job_records import AnalysisJob as AnalysisJob
from spotify_manager.interfaces.http.job_records import PlaylistJob as PlaylistJob
from spotify_manager.interfaces.http.job_registry import lookup_job as lookup_job
from spotify_manager.interfaces.http.job_registry import register_job
from spotify_manager.interfaces.http.job_registry import require_slot
from spotify_manager.interfaces.http.logging import JobLogFormatter
from spotify_manager.interfaces.http.models.analysis import (
    AnalysisJobLog as AnalysisJobLog,
)
from spotify_manager.interfaces.http.models.analysis import (
    AnalysisJobResult as AnalysisJobResult,
)
from spotify_manager.interfaces.http.models.analysis import (
    AnalysisResourceProgress as AnalysisResourceProgress,
)
from spotify_manager.interfaces.http.models.common import CommandResult as CommandResult
from spotify_manager.interfaces.http.models.common import CountResult as CountResult
from spotify_manager.interfaces.http.models.common import JobStatus as JobStatus
from spotify_manager.interfaces.http.models.common import (
    LibraryMirrorFilesStatus as LibraryMirrorFilesStatus,
)
from spotify_manager.interfaces.http.models.common import (
    ServerFileStatus as ServerFileStatus,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyArtistResult as DiscographyArtistResult,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyChoiceRequest as DiscographyChoiceRequest,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyPendingChoice as DiscographyPendingChoice,
)
from spotify_manager.interfaces.http.models.discography import (
    DiscographyReleaseOption as DiscographyReleaseOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsChoiceRequest as NewKidsChoiceRequest,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsFillResult as NewKidsFillResult,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsPendingChoice as NewKidsPendingChoice,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsReleaseOption as NewKidsReleaseOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    NewKidsTrackResult as NewKidsTrackResult,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3AnnualImportEntry as Queue3AnnualImportEntry,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ChoiceRequest as Queue3ChoiceRequest,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ComposerPlaylistOption as Queue3ComposerPlaylistOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3PendingChoice as Queue3PendingChoice,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ReleaseOption as Queue3ReleaseOption,
)
from spotify_manager.interfaces.http.models.discovery import (
    Queue3TrackResult as Queue3TrackResult,
)
from spotify_manager.interfaces.http.models.historical import (
    BlastSelectionResult as BlastSelectionResult,
)
from spotify_manager.interfaces.http.models.historical import (
    DormantArtistResultEntry as DormantArtistResultEntry,
)
from spotify_manager.interfaces.http.models.jobs import BlastJobResult as BlastJobResult
from spotify_manager.interfaces.http.models.palace import (
    PalaceAlbumRefreshResult as PalaceAlbumRefreshResult,
)
from spotify_manager.interfaces.http.models.palace import (
    PalaceAlbumSelectionResult as PalaceAlbumSelectionResult,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueArtistOption as QueueArtistOption,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueChoiceRequest as QueueChoiceRequest,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueFillResultEntry as QueueFillResultEntry,
)
from spotify_manager.interfaces.http.models.queue import (
    QueueFlushResultEntry as QueueFlushResultEntry,
)
from spotify_manager.interfaces.http.models.queue import (
    QueuePendingChoice as QueuePendingChoice,
)
from spotify_manager.interfaces.http.models.recommendations import (
    FoundArtSelectionResult as FoundArtSelectionResult,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonAlbumOption as SauvignonAlbumOption,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonChoiceRequest as SauvignonChoiceRequest,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonPendingChoice as SauvignonPendingChoice,
)
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonSelectionResult as SauvignonSelectionResult,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckArtistOption as ReleaseCheckArtistOption,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckChoiceRequest as ReleaseCheckChoiceRequest,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckPendingChoice as ReleaseCheckPendingChoice,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckResultEntry as ReleaseCheckResultEntry,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckStateRestoreRequest as ReleaseCheckStateRestoreRequest,
)
from spotify_manager.interfaces.http.models.releases import (
    ReleaseCheckStateSnapshot as ReleaseCheckStateSnapshot,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningChoiceRequest as SlowListeningChoiceRequest,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningPendingChoice as SlowListeningPendingChoice,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningReleaseOption as SlowListeningReleaseOption,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningTrackResult as SlowListeningTrackResult,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldArtistOption as SomethingOldArtistOption,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldChoiceRequest as SomethingOldChoiceRequest,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldPendingChoice as SomethingOldPendingChoice,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldRankingEntry as SomethingOldRankingEntry,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldReleaseOption as SomethingOldReleaseOption,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldTrackResult as SomethingOldTrackResult,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateNamespaceReplaceRequest as SharedStateNamespaceReplaceRequest,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateReplaceRequest as SharedStateReplaceRequest,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateSnapshot as SharedStateSnapshot,
)
from spotify_manager.interfaces.http.models.state import (
    SharedStateSummary as SharedStateSummary,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineCellarTrackResult as NewWineCellarTrackResult,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineChoiceRequest as NewWineChoiceRequest,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWinePendingChoice as NewWinePendingChoice,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineRefillResult as NewWineRefillResult,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineReleaseOption as NewWineReleaseOption,
)
from spotify_manager.interfaces.http.models.wine import (
    NewWineTrackResult as NewWineTrackResult,
)
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.playlist_retry import (
    PlaylistRetry as PlaylistRetry,
)
from spotify_manager.interfaces.http.presenters.discovery import (
    _apply_queue_3_annual_summary as _apply_queue_3_annual_summary,
)
from spotify_manager.interfaces.http.presenters.discovery import (
    _apply_queue_3_flush_summary as _apply_queue_3_flush_summary,
)
from spotify_manager.interfaces.http.workers.blast import BlastWorker as BlastWorker
from spotify_manager.interfaces.http.workers.blast_artist import (
    BlastArtistWorker as BlastArtistWorker,
)
from spotify_manager.interfaces.http.workers.daily_mind_radio import (
    DailyMindRadioWorker as DailyMindRadioWorker,
)
from spotify_manager.interfaces.http.workers.discography import (
    DiscographyWorker as DiscographyWorker,
)
from spotify_manager.interfaces.http.workers.errors import (
    _DiscographyJobCancelledError as _DiscographyJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _NewKidsJobCancelledError as _NewKidsJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _NewWineJobCancelledError as _NewWineJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _PalaceOfMemoryJobCancelledError as _PalaceOfMemoryJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _Queue3JobCancelledError as _Queue3JobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _QueueJobCancelledError as _QueueJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _ReleaseCheckJobCancelledError as _ReleaseCheckJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _RequeueForADreamJobCancelledError as _RequeueForADreamJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _SauvignonJobCancelledError as _SauvignonJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _SlowListeningJobCancelledError as _SlowListeningJobCancelledError,
)
from spotify_manager.interfaces.http.workers.errors import (
    _SomethingOldJobCancelledError as _SomethingOldJobCancelledError,
)
from spotify_manager.interfaces.http.workers.found_art import (
    FoundArtWorker as FoundArtWorker,
)
from spotify_manager.interfaces.http.workers.new_kids import (
    NewKidsWorker as NewKidsWorker,
)
from spotify_manager.interfaces.http.workers.new_wine import (
    NewWineWorker as NewWineWorker,
)
from spotify_manager.interfaces.http.workers.new_year import (
    NewYearWorker as NewYearWorker,
)
from spotify_manager.interfaces.http.workers.palace_of_memory import (
    PalaceOfMemoryWorker as PalaceOfMemoryWorker,
)
from spotify_manager.interfaces.http.workers.queue_3 import Queue3Worker as Queue3Worker
from spotify_manager.interfaces.http.workers.queue_fill import (
    QueueFillWorker as QueueFillWorker,
)
from spotify_manager.interfaces.http.workers.queue_flush import (
    QueueFlushWorker as QueueFlushWorker,
)
from spotify_manager.interfaces.http.workers.release_check import (
    ReleaseCheckWorker as ReleaseCheckWorker,
)
from spotify_manager.interfaces.http.workers.requeue_for_a_dream import (
    RequeueForADreamWorker as RequeueForADreamWorker,
)
from spotify_manager.interfaces.http.workers.sauvignon import (
    SauvignonWorker as SauvignonWorker,
)
from spotify_manager.interfaces.http.workers.scrobble_history import (
    ScrobbleHistoryWorker as ScrobbleHistoryWorker,
)
from spotify_manager.interfaces.http.workers.slow_listening import (
    SlowListeningWorker as SlowListeningWorker,
)
from spotify_manager.interfaces.http.workers.something_old import (
    SomethingOldWorker as SomethingOldWorker,
)
from spotify_manager.interfaces.lookup_operations import (
    evaluate_live_album as evaluate_album_live,
)
from spotify_manager.interfaces.lookup_operations import (
    get_live_artist_library_stats as get_live_artist_library_stats,
)
from spotify_manager.interfaces.lookup_operations import (
    get_track_scrobble_status as get_track_scrobble_status,
)
from spotify_manager.interfaces.operations import analyse_library as library_analysis
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import (
    blast_from_past_artists as blast_from_past_artists,
)
from spotify_manager.interfaces.operations import daily_mind_radio as daily_mind_radio
from spotify_manager.interfaces.operations import discography as discography
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import genre_reveal as genre_reveal
from spotify_manager.interfaces.operations import new_kids as new_kids
from spotify_manager.interfaces.operations import new_wine as new_wine
from spotify_manager.interfaces.operations import new_year as new_year
from spotify_manager.interfaces.operations import palace_of_memory as palace_of_memory
from spotify_manager.interfaces.operations import queue_3 as queue_3
from spotify_manager.interfaces.operations import (
    recover_removed_albums as recover_removed_albums,
)
from spotify_manager.interfaces.operations import release_check as release_check
from spotify_manager.interfaces.operations import (
    requeue_for_a_dream as requeue_for_a_dream,
)
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import review_artists as review_artists
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.interfaces.operations import slow_listening as slow_listening
from spotify_manager.interfaces.operations import something_old as something_old
from spotify_manager.interfaces.operations import the_queue as the_queue
from spotify_manager.interfaces.operations.legacy_library import (
    analyse_comparison as analyse_comparison,
)
from spotify_manager.interfaces.operations.legacy_library import (
    compare_your_library_and_all_albums as compare_your_library_and_all_albums,
)
from spotify_manager.interfaces.operations.legacy_library import (
    convert_your_library_file as convert_your_library_file,
)
from spotify_manager.interfaces.operations.legacy_library import (
    count_artists_in_library as count_artists_in_library,
)
from spotify_manager.interfaces.operations.legacy_library import (
    restore_your_library_from_file as restore_your_library_from_file,
)
from spotify_manager.interfaces.operations.legacy_library import (
    run_monthly_routines as run_monthly_routines,
)
from spotify_manager.interfaces.operations.legacy_library import (
    update_total_album_list as update_total_album_list,
)
from spotify_manager.interfaces.requests.discovery import DiscoveryOptions
from spotify_manager.interfaces.requests.palace import PalaceOptions
from spotify_manager.interfaces.requests.queue_3 import Queue3Options
from spotify_manager.interfaces.requests.queue_fill import QueueFillOptions
from spotify_manager.interfaces.requests.release_check import ReleaseCheckOptions
from spotify_manager.interfaces.requests.sauvignon import SauvignonOptions
from spotify_manager.interfaces.requests.something_old import SomethingOldOptions
from spotify_manager.loaders_savers import (
    load_your_library_file as load_your_library_file,
)
from spotify_manager.models.lookups import AlbumEvaluation as AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats as ArtistLibraryStats
from spotify_manager.models.lookups import TrackScrobbleStatus as TrackScrobbleStatus
from spotify_manager.models.your_library import YourLibraryFile as YourLibraryFile
from spotify_manager.processors.library_lookups import (
    AlbumNotFoundError as AlbumNotFoundError,
)
from spotify_manager.processors.library_lookups import (
    AmbiguousAlbumError as AmbiguousAlbumError,
)
from spotify_manager.processors.library_lookups import (
    AmbiguousArtistError as AmbiguousArtistError,
)
from spotify_manager.processors.library_lookups import (
    ArtistNotFoundError as ArtistNotFoundError,
)
from spotify_manager.processors.library_lookups import (
    SpotifyLookupResponseError as SpotifyLookupResponseError,
)
from spotify_manager.processors.library_lookups import (
    parse_spotify_lookup_reference as parse_spotify_lookup_reference,
)
from spotify_manager.processors.scrobble_lookups import (
    AmbiguousTrackError as AmbiguousTrackError,
)
from spotify_manager.processors.scrobble_lookups import (
    TrackNotFoundError as TrackNotFoundError,
)
from spotify_manager.routines import composer_playlists as composer_playlists
from spotify_manager.settings import Settings as Settings


__all__ = ["evaluate_album_live", "sauvignon"]


def _new_year_default_state() -> dict[str, object]:
    return {"years": {}}


STATE_NAMESPACE_DEFINITIONS: dict[str, StateDefinition] = {
    "discography": DiscographyStateCodec(),
    "genre_reveal": GenreRevealStateCodec(),
    "new_kids": NewKidsStateCodec(),
    "new_wine": NewWineStateCodec(),
    "new_year": NewYearStateDefinition(),
    "palace_of_memory": PalaceOfMemoryStateCodec(),
    "queue": TheQueueStateCodec(),
    "queue_3": Queue3StateCodec(),
    "recover_removed_albums": RecoverRemovedAlbumsStateCodec(),
    "release_check": ReleaseCheckStateCodec(),
    "review_album_limits": ReviewAlbumLimitsStateCodec(),
    "review_artists": ReviewArtistsStateCodec(),
    "slow_listening": SlowListeningStateCodec(),
}

_AnalysisJob = AnalysisJob

_BlastJob = PlaylistJob

_analysis_jobs: dict[str, _AnalysisJob] = {}

_analysis_jobs_lock = Lock()

_MAX_ANALYSIS_LOGS = 250

_analysis_logger = logging.getLogger(__name__)

_blast_jobs: dict[str, _BlastJob] = {}

_blast_jobs_lock = Lock()

_MAX_BLAST_LOGS = 250

LIBRARY_MIRROR_FILE_PATHS = (
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.albums_total,
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.liked_tracks_total,
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.artists_total,
    scrobble_history.DEFAULT_SCROBBLES_PATH,
)

RELEASE_CHECK_STATE_PATH = Path(
    os.environ.get("RELEASE_CHECK_STATE_PATH", release_check.DEFAULT_STATE_PATH)
)

RELEASE_CHECK_STATE_BACKUP_DIR = Path(
    os.environ.get(
        "RELEASE_CHECK_STATE_BACKUP_DIR", release_check.DEFAULT_STATE_BACKUP_DIR
    )
)

SPOTIFY_CONNECTION_FAILURE_DETAIL = (
    "Spotify connection remained unavailable after "
    "automatic retries. Please try again shortly."
)

DEFAULT_SPOTIFY_RATE_LIMIT_RETRY_SECONDS = 60


async def get_client() -> Spotify:
    """Acquire the lifespan-owned standard native client.

    Returns:
        Native client with the original standard retry profile.
    """
    return await current_execution().client()


async def get_analysis_client() -> Spotify:
    """Acquire the lifespan-owned mirror-analysis native client.

    Returns:
        Native client with the original disabled adapter retry profile.
    """
    return await current_execution().client("analysis")


async def get_interactive_client() -> Spotify:
    """Acquire the lifespan-owned interactive native client.

    Returns:
        Native client with the original disabled adapter retry profile.
    """
    return await current_execution().client("interactive")


@lru_cache
def get_library() -> YourLibraryFile:
    """Provide the parsed YourLibrary.json, cached for the process."""
    return load_your_library_file()


ClientDep = Annotated[Spotify, Depends(get_client)]

AnalysisClientDep = Annotated[Spotify, Depends(get_analysis_client)]

InteractiveClientDep = Annotated[Spotify, Depends(get_interactive_client)]

LibraryDep = Annotated[YourLibraryFile, Depends(get_library)]


def _job_snapshot(job: _AnalysisJob) -> AnalysisJobResult:
    """Return an isolated response model for one mutable job."""
    return job.result.model_copy(deep=True)


def _append_job_log_locked(job: _AnalysisJob, message: str) -> None:
    """Append one bounded log entry while the caller holds the jobs lock."""
    if not message:
        return
    job.next_log_sequence = append_log(
        job.result.logs, job.next_log_sequence, message, JobLogFormatter(datetime)
    )
    retain_logs(job.result.logs, _MAX_ANALYSIS_LOGS)


def _blast_job_snapshot(job: _BlastJob) -> BlastJobResult:
    """Return an isolated response model for one mutable playlist job."""
    return job.result.model_copy(deep=True)


def _append_blast_log_locked(job: _BlastJob, message: str) -> None:
    """Append one bounded playlist-job log entry while holding its lock."""
    if not message:
        return
    job.next_log_sequence = append_log(
        job.result.logs, job.next_log_sequence, message, JobLogFormatter(datetime)
    )
    retain_logs(job.result.logs, _MAX_BLAST_LOGS)


def _create_job_log(sequence: int, message: str) -> AnalysisJobLog:
    return AnalysisJobLog(
        sequence=sequence, timestamp=datetime.now(UTC).isoformat(), message=message
    )


def _analysis_job_identities() -> Iterator[JobIdentity]:
    for job in _analysis_jobs.values():
        yield job.result


def _playlist_job_identities() -> Iterator[JobIdentity]:
    for job in _blast_jobs.values():
        yield job.result


def _require_analysis_slot(command: str) -> None:
    """Keep the original command-scoped conflict while the registry is locked.

    Args:
        command: Original analysis command requesting reservation.

    Raises:
        HTTPException: A matching active analysis retains its original 409 detail.
    """
    require_slot(
        _analysis_job_identities(),
        "an analysis of this type is already running",
        command,
    )


def _require_playlist_slot(message: str) -> None:
    """Keep the original shared playlist/history conflict under its registry lock.

    Args:
        message: Original feature-specific conflict text.

    Raises:
        HTTPException: An active playlist/history job retains its original detail.
    """
    require_slot(_playlist_job_identities(), message, include_command=True)


def _release_check_state_snapshot(
    known_fingerprint: str | None = None, *, backup_path: Path | None = None
) -> ReleaseCheckStateSnapshot:
    """Load one state snapshot, omitting its body when the browser is current."""
    state = (
        get_state_service().namespace("release_check", ReleaseCheckStateCodec()).load()
    )
    fingerprint = release_check.state_fingerprint(state)
    return ReleaseCheckStateSnapshot(
        updated_at=release_check.state_updated_at(state),
        fingerprint=fingerprint,
        state=None if fingerprint == known_fingerprint else state,
        backup_path=str(backup_path) if backup_path is not None else None,
    )


def _state_timestamp(value: str | None) -> datetime | None:
    """Parse one state freshness timestamp as UTC."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _release_state_is_newer(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    """Return whether a browser-held state is semantically newer."""
    candidate_at = _state_timestamp(release_check.state_updated_at(candidate))
    current_at = _state_timestamp(release_check.state_updated_at(current))
    return candidate_at is not None and (
        current_at is None or candidate_at > current_at
    )


def get_analysis_job(job_id: str) -> _AnalysisJob:
    """Return one job or raise a conventional API 404."""
    return lookup_job(
        _analysis_jobs, _analysis_jobs_lock, job_id, "analysis job not found"
    )


def get_blast_job(job_id: str, command: str | None = None) -> _BlastJob:
    """Return one playlist job or raise a conventional API 404."""
    return lookup_job(
        _blast_jobs, _blast_jobs_lock, job_id, "playlist job not found", command
    )


def _cancel_simple_playlist_job(
    job_id: str, *, command: str, detail: str
) -> BlastJobResult:
    """Signal a non-interactive playlist worker to stop cleanly."""
    job = get_blast_job(job_id, command=command)
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="Playlist job is not active")
        job.result.status = "cancelling"
        job.result.detail = detail
        _append_blast_log_locked(job, detail)
        job.cancel_event.set()
        return _blast_job_snapshot(job)


async def _run_analysis_job(
    job_id: str,
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None,
    full_rebuild: bool = False,
    mirror_resource: library_analysis.ResourceName | None = None,
) -> None:
    """Execute one analysis worker and translate outcomes into job state."""
    worker = _analysis_worker(job_id, mode, spotify, full_rebuild, mirror_resource)
    worker.start()
    events = SpotifyEvents(spotify)
    events.subscribe(worker)
    try:
        summary = await worker.execute()
    except library_analysis.LibraryAnalysisCancelledError as exc:
        worker.cancelled(exc)
    except library_analysis.SpotifyRateLimitError as exc:
        worker.paused(exc)
    except library_analysis.LibrarySyncError as exc:
        worker.failed(exc)
    except Exception as exc:
        _analysis_logger.exception("Unexpected library analysis error")
        worker.unexpected_failure(exc)
    else:
        worker.completed(summary)
    finally:
        events.restore()
        worker.finish()


def _analysis_worker(
    job_id: str,
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None,
    full_rebuild: bool,
    mirror_resource: library_analysis.ResourceName | None,
) -> AnalysisWorker:
    return AnalysisWorker(
        job=get_analysis_job(job_id),
        context=AnalysisContext(_analysis_jobs_lock, datetime, _MAX_ANALYSIS_LOGS),
        mode=mode,
        spotify=spotify,
        full_rebuild=full_rebuild,
        mirror_resource=mirror_resource,
    )


def _job_time() -> datetime:
    return datetime.now(UTC)


async def start_analysis_job(
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None = None,
    full_rebuild: bool = False,
    mirror_resource: library_analysis.ResourceName | None = None,
) -> AnalysisJobResult:
    """Start one background analysis, rejecting duplicate active modes.

    Args:
        mode: Original library analysis mode.
        spotify: Caller-owned Spotify client.
        full_rebuild: Whether to discard prior incremental progress.
        mirror_resource: Optional mirror scope.

    Returns:
        Original operation result.
    """
    if mode == "mirrors" and mirror_resource is not None:
        command = f"refresh_library_mirror_{mirror_resource}"
    else:
        command = (
            "refresh_library_mirrors"
            if mode == "mirrors"
            else f"analyse_library_{mode}"
        )
    is_full_rebuild = mode == "mirrors" and full_rebuild
    resources = (
        (mirror_resource,)
        if mirror_resource is not None
        else ("albums", "tracks")
        if mode == "mirrors"
        else ("albums", "tracks", "artists")
    )
    with _analysis_jobs_lock:
        _require_analysis_slot(command)
        job_id = uuid4().hex
        job = _AnalysisJob(
            result=AnalysisJobResult(
                job_id=job_id,
                command=command,
                full_rebuild=is_full_rebuild,
                mirror_resource=mirror_resource,
                resources=_analysis_resources(resources),
            ),
            cancel_event=Event(),
        )
        _append_job_log_locked(job, f"{mode.title()} analysis queued.")
        register_job(_analysis_jobs, job_id, job)
        snapshot = _job_snapshot(job)
    current_execution().jobs.start(
        _run_analysis_job(job_id, mode, spotify, full_rebuild, mirror_resource),
        job.cancel_event,
        f"library-analysis-{mode}-{job_id[:8]}",
    )
    return snapshot


def _playlist_job_retry(job: _BlastJob, echo: Messages) -> blast_from_past.RetryCall:
    """Build a bounded Spotify retry policy with interruptible waits."""
    return PlaylistRetry(job, echo)


class JobConfiguration:
    """Observe HTTP configuration at the original worker setup boundary."""

    def load(self) -> Settings:
        """Read current environment-backed settings.

        Returns:
            Original settings model.
        """
        return Settings()


def _playlist_context() -> PlaylistContext:
    return PlaylistContext(
        registry=_blast_jobs,
        lock=_blast_jobs_lock,
        logger=_analysis_logger,
        clock=datetime,
        settings=JobConfiguration(),
        log_limit=_MAX_BLAST_LOGS,
    )


async def _run_blast_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
    dry_run: bool,
) -> None:
    """Execute one web playlist job and retain progress, logs, and results."""
    await BlastWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        count=count,
        max_playlist_length=max_playlist_length,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
    ).run()


async def _run_blast_artist_job(
    job_id: str, spotify: Spotify, playlist_id: str, count: int, dry_run: bool
) -> None:
    """Execute one alphabetic dormant-artist playlist update."""
    await BlastArtistWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        count=count,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
    ).run()


async def _run_daily_mind_radio_job(
    job_id: str, spotify: Spotify, playlist_id: str, dry_run: bool
) -> None:
    """Execute one Daily Mind Radio web job and retain its complete trace."""
    await DailyMindRadioWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
    ).run()


async def _run_found_art_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int,
) -> None:
    """Execute one Found Art web job and retain its complete trace."""
    await FoundArtWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        api_key=api_key,
        username=username,
        count=count,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
    ).run()


async def _run_sauvignon_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> None:
    """Run reconnectable Last.fm album discovery for Sauvignon."""
    await SauvignonWorker(
        job_id=job_id,
        spotify=spotify,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
        options=SauvignonOptions(
            seed_count=seed_count,
            max_playlist_length=max_playlist_length,
            playlist_id=playlist_id,
            dry_run=dry_run,
            count=count,
        ),
        credentials=LastFmCredentials(api_key, username),
    ).run()


async def _run_queue_fill_job(
    job_id: str,
    spotify: Spotify,
    playlists: the_queue.QueuePlaylists,
    api_key: str,
    username: str,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> None:
    """Run reconnectable Last.fm artist discovery for The Queue."""
    await QueueFillWorker(
        job_id=job_id,
        spotify=spotify,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
        options=QueueFillOptions(
            playlists=playlists,
            max_playlist_length=max_playlist_length,
            seed_count=seed_count,
            dry_run=dry_run,
            count=count,
        ),
        credentials=LastFmCredentials(api_key, username),
    ).run()


async def _run_queue_flush_job(
    job_id: str, spotify: Spotify, playlists: the_queue.QueuePlaylists, dry_run: bool
) -> None:
    """Run the first-ten-artist Queue flush as a reconnectable web job."""
    await QueueFlushWorker(
        job_id=job_id,
        spotify=spotify,
        playlists=playlists,
        dry_run=dry_run,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
    ).run()


async def _run_new_kids_job(
    job_id: str,
    spotify: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    dry_run: bool,
    command: Literal["flush_new_kids", "flush_queue_2"] = "flush_new_kids",
) -> None:
    """Execute one interactive album-discovery flush as a reconnectable job."""
    await NewKidsWorker(
        job_id=job_id,
        spotify=spotify,
        command=command,
        rate_limit_delay=DEFAULT_SPOTIFY_RATE_LIMIT_RETRY_SECONDS,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
        options=DiscoveryOptions(
            dry_run=dry_run,
            new_kids_playlist_id=new_kids_playlist_id,
            great_discoveries_2026_playlist_id=great_discoveries_playlist_id,
            newfoundland_playlist_id=newfoundland_playlist_id,
            unlucky_ones_playlist_id=unlucky_ones_playlist_id,
            queue_2_playlist_id=queue_2_playlist_id,
        ),
    ).run()


async def _run_queue_3_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
    annual_only: bool = False,
) -> None:
    """Execute one Queue 3 operation as a reconnectable web job."""
    await Queue3Worker(
        job_id=job_id,
        spotify=spotify,
        annual_only=annual_only,
        connection_failure=SPOTIFY_CONNECTION_FAILURE_DETAIL,
        context=_playlist_context(),
        options=Queue3Options(playlist_id=playlist_id or "", dry_run=dry_run),
    ).run()


async def _run_new_wine_job(
    job_id: str,
    spotify: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    wine_cellar_playlist_id: str,
    dry_run: bool,
    no_discovery: bool,
    choose_album_endpoints: bool = False,
) -> None:
    """Execute one interactive New Wine flush as a reconnectable web job."""
    await NewWineWorker(
        job_id=job_id,
        spotify=spotify,
        rate_limit_delay=DEFAULT_SPOTIFY_RATE_LIMIT_RETRY_SECONDS,
        context=_playlist_context(),
        options=NewWineOptions(
            no_discovery=no_discovery,
            destination=new_wine_playlist_id,
            dry_run=dry_run,
            cellar=wine_cellar_playlist_id,
            endpoint_mode=choose_album_endpoints,
            sauvignon=sauvignon_playlist_id,
        ),
    ).run()


async def _run_slow_listening_job(
    job_id: str, spotify: Spotify, playlist_id: str, dry_run: bool
) -> None:
    """Execute an interactive Slow Listening flush as a reconnectable job."""
    await SlowListeningWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        context=_playlist_context(),
    ).run()


async def _run_something_old_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Execute Something Old as a reconnectable interactive web job."""
    await SomethingOldWorker(
        job_id=job_id,
        spotify=spotify,
        context=_playlist_context(),
        options=SomethingOldOptions(
            playlist_id=playlist_id, dry_run=dry_run, expected_username=username
        ),
        credentials=LastFmCredentials(api_key, username),
    ).run()


async def _run_release_check_job(
    job_id: str,
    spotify: Spotify,
    playlists: release_check.ReleaseCheckPlaylists,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Execute one reconnectable, interactive new-release check."""
    await ReleaseCheckWorker(
        RELEASE_CHECK_STATE_PATH=RELEASE_CHECK_STATE_PATH,
        job_id=job_id,
        spotify=spotify,
        context=_playlist_context(),
        options=ReleaseCheckOptions(
            playlists=playlists, dry_run=dry_run, expected_username=username
        ),
        credentials=LastFmCredentials(api_key, username),
    ).run()


async def _run_discography_job(
    job_id: str,
    spotify: Spotify,
    playlist_ids: dict[discography.QueueName, str],
    queue_3_playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute one reload-safe interactive discography planning job."""
    await DiscographyWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_ids=playlist_ids,
        queue_3_playlist_id=queue_3_playlist_id,
        dry_run=dry_run,
        context=_playlist_context(),
    ).run()


async def _run_requeue_for_a_dream_job(
    job_id: str, spotify: Spotify, playlist_id: str, dry_run: bool
) -> None:
    """Execute one reconnectable Requeue for a Dream transition."""
    await RequeueForADreamWorker(
        job_id=job_id,
        spotify=spotify,
        playlist_id=playlist_id,
        dry_run=dry_run,
        context=_playlist_context(),
    ).run()


async def _run_palace_of_memory_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str | None,
    dry_run: bool,
    alphabetical_start: str | None,
    cursor_position: int | None,
) -> None:
    """Execute one reconnectable Palace fill or cursor adjustment."""
    await PalaceOfMemoryWorker(
        job_id=job_id,
        spotify=spotify,
        cursor_position=cursor_position,
        context=_playlist_context(),
        options=PalaceOptions(
            alphabetical_start=alphabetical_start,
            playlist_id=playlist_id or "",
            dry_run=dry_run,
        ),
    ).run()


async def _run_scrobble_history_job(
    job_id: str, api_key: str, username: str, dry_run: bool, full_rebuild: bool = False
) -> None:
    """Refresh the shared Last.fm record as a reconnectable web job."""
    await ScrobbleHistoryWorker(
        job_id=job_id,
        api_key=api_key,
        username=username,
        dry_run=dry_run,
        full_rebuild=full_rebuild,
        context=_playlist_context(),
    ).run()


async def start_blast_job(
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
    dry_run: bool,
) -> BlastJobResult:
    """Start one playlist job, rejecting another active invocation.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        count: Requested number of selections.
        max_playlist_length: Existing playlist size limit.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(result=BlastJobResult(job_id=job_id, dry_run=dry_run))
        _append_blast_log_locked(
            job,
            "A blast from the past queued" + (" in dry-run mode." if dry_run else "."),
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_blast_job(
                job_id, spotify, playlist_id, count, max_playlist_length, dry_run
            )
        ),
        job.cancel_event,
        f"blast-from-the-past-{job_id[:8]}",
    )
    return snapshot


async def start_blast_artist_job(
    spotify: Spotify, playlist_id: str, count: int, dry_run: bool
) -> BlastJobResult:
    """Start one dormant-artist recovery job.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        count: Requested number of selections.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="blast_from_the_past_artists",
                requested_count=count,
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            "Dormant-artist recovery queued"
            + (" in dry-run mode." if dry_run else "."),
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        _run_blast_artist_job(job_id, spotify, playlist_id, count, dry_run),
        job.cancel_event,
        f"blast-from-the-past-artists-{job_id[:8]}",
    )
    return snapshot


async def start_daily_mind_radio_job(
    spotify: Spotify, playlist_id: str, dry_run: bool
) -> BlastJobResult:
    """Start one Daily Mind Radio job, rejecting another playlist routine.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="daily_mind_radio", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job, "Daily Mind Radio queued" + (" in dry-run mode." if dry_run else ".")
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        _run_daily_mind_radio_job(job_id, spotify, playlist_id, dry_run),
        job.cancel_event,
        f"daily-mind-radio-{job_id[:8]}",
    )
    return snapshot


async def start_found_art_job(
    spotify: Spotify, playlist_id: str, api_key: str, username: str, count: int
) -> BlastJobResult:
    """Start one Found Art job, rejecting another playlist routine.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        api_key: Configured Last.fm API credential.
        username: Configured Last.fm username.
        count: Requested number of selections.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="found_art", requested_count=count
            )
        )
        _append_blast_log_locked(job, "Found Art queued.")
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (_run_found_art_job(job_id, spotify, playlist_id, api_key, username, count)),
        job.cancel_event,
        f"found-art-{job_id[:8]}",
    )
    return snapshot


async def start_sauvignon_job(
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    *,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> BlastJobResult:
    """Start a Sauvignon album-discovery job, rejecting playlist overlap.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        api_key: Configured Last.fm API credential.
        username: Configured Last.fm username.
        count: Requested number of selections.
        max_playlist_length: Existing playlist size limit.
        seed_count: Requested recommendation seed count.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_sauvignon_from_lastfm",
                requested_count=count,
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            "Sauvignon album discovery queued"
            + (" in dry-run mode." if dry_run else "."),
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_sauvignon_job(
                job_id,
                spotify,
                playlist_id,
                api_key,
                username,
                count,
                max_playlist_length,
                seed_count,
                dry_run,
            )
        ),
        job.cancel_event,
        f"sauvignon-fill-{job_id[:8]}",
    )
    return snapshot


async def start_queue_fill_job(
    spotify: Spotify,
    playlists: the_queue.QueuePlaylists,
    api_key: str,
    username: str,
    *,
    count: int | None,
    max_playlist_length: int | None,
    seed_count: int,
    dry_run: bool,
) -> BlastJobResult:
    """Start a Queue artist-discovery job, rejecting playlist overlap.

    Args:
        spotify: Caller-owned Spotify client.
        playlists: Configured playlist identities.
        api_key: Configured Last.fm API credential.
        username: Configured Last.fm username.
        count: Requested number of selections.
        max_playlist_length: Existing playlist size limit.
        seed_count: Requested recommendation seed count.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_queue_from_lastfm",
                requested_count=count,
                queue_max_playlist_length=max_playlist_length,
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            f"Queue artist discovery queued{(' in dry-run mode' if dry_run else '')}.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_queue_fill_job(
                job_id,
                spotify,
                playlists,
                api_key,
                username,
                count,
                max_playlist_length,
                seed_count,
                dry_run,
            )
        ),
        job.cancel_event,
        f"queue-fill-{job_id[:8]}",
    )
    return snapshot


async def start_queue_flush_job(
    spotify: Spotify, playlists: the_queue.QueuePlaylists, *, dry_run: bool
) -> BlastJobResult:
    """Start a Queue flush job, rejecting another playlist routine.

    Args:
        spotify: Caller-owned Spotify client.
        playlists: Configured playlist identities.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(job_id=job_id, command="flush_queue", dry_run=dry_run)
        )
        _append_blast_log_locked(
            job, f"Queue flush queued{(' in dry-run mode' if dry_run else '')}."
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        _run_queue_flush_job(job_id, spotify, playlists, dry_run),
        job.cancel_event,
        f"queue-flush-{job_id[:8]}",
    )
    return snapshot


async def start_new_kids_job(
    spotify: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one New Kids web job, rejecting another playlist routine.

    Args:
        spotify: Caller-owned Spotify client.
        new_kids_playlist_id: Configured new kids playlist identity.
        queue_2_playlist_id: Configured queue 2 playlist identity.
        great_discoveries_playlist_id: Configured great discoveries playlist identity.
        unlucky_ones_playlist_id: Configured unlucky ones playlist identity.
        newfoundland_playlist_id: Configured newfoundland playlist identity.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_new_kids", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job, f"New Kids flush queued{(' in dry-run mode' if dry_run else '')}."
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_new_kids_job(
                job_id,
                spotify,
                new_kids_playlist_id,
                queue_2_playlist_id,
                great_discoveries_playlist_id,
                unlucky_ones_playlist_id,
                newfoundland_playlist_id,
                dry_run,
            )
        ),
        job.cancel_event,
        f"new-kids-flush-{job_id[:8]}",
    )
    return snapshot


async def start_queue_2_job(
    spotify: Spotify,
    new_kids_playlist_id: str,
    queue_2_playlist_id: str,
    great_discoveries_playlist_id: str,
    unlucky_ones_playlist_id: str,
    newfoundland_playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one Queue 2 web job, rejecting another playlist routine.

    Args:
        spotify: Caller-owned Spotify client.
        new_kids_playlist_id: Configured new kids playlist identity.
        queue_2_playlist_id: Configured queue 2 playlist identity.
        great_discoveries_playlist_id: Configured great discoveries playlist identity.
        unlucky_ones_playlist_id: Configured unlucky ones playlist identity.
        newfoundland_playlist_id: Configured newfoundland playlist identity.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_queue_2", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job, f"Queue 2 flush queued{(' in dry-run mode' if dry_run else '')}."
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_new_kids_job(
                job_id,
                spotify,
                new_kids_playlist_id,
                queue_2_playlist_id,
                great_discoveries_playlist_id,
                unlucky_ones_playlist_id,
                newfoundland_playlist_id,
                dry_run,
                "flush_queue_2",
            )
        ),
        job.cancel_event,
        f"queue-2-flush-{job_id[:8]}",
    )
    return snapshot


async def start_queue_3_job(
    spotify: Spotify, playlist_id: str, *, dry_run: bool, annual_only: bool = False
) -> BlastJobResult:
    """Start one Queue 3 flush or standalone annual-import web job.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        dry_run: Whether to preview without durable writes.
        annual_only: Whether to import annual discoveries only.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_queue_3",
                dry_run=dry_run,
                queue_3_annual_only=annual_only,
            )
        )
        _append_blast_log_locked(
            job,
            ("Previous-year Queue 3 import" if annual_only else "Queue 3 flush")
            + f" queued{(' in dry-run mode' if dry_run else '')}.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        _run_queue_3_job(job_id, spotify, playlist_id, dry_run, annual_only),
        job.cancel_event,
        f"queue-3-{('import' if annual_only else 'flush')}-{job_id[:8]}",
    )
    return snapshot


async def start_new_wine_job(
    spotify: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    wine_cellar_playlist_id: str,
    *,
    dry_run: bool,
    no_discovery: bool,
    choose_album_endpoints: bool = False,
) -> BlastJobResult:
    """Start one New Wine web job, rejecting another playlist routine.

    Args:
        spotify: Caller-owned Spotify client.
        new_wine_playlist_id: Configured new wine playlist identity.
        sauvignon_playlist_id: Configured sauvignon playlist identity.
        wine_cellar_playlist_id: Configured wine cellar playlist identity.
        dry_run: Whether to preview without durable writes.
        no_discovery: Whether to skip new discovery candidates.
        choose_album_endpoints: Whether to ask for release endpoints.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_new_wine",
                dry_run=dry_run,
                no_discovery=no_discovery,
                choose_album_endpoints=choose_album_endpoints,
            )
        )
        _append_blast_log_locked(
            job, f"New Wine flush queued{(' in dry-run mode' if dry_run else '')}."
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_new_wine_job(
                job_id,
                spotify,
                new_wine_playlist_id,
                sauvignon_playlist_id,
                wine_cellar_playlist_id,
                dry_run,
                no_discovery,
                choose_album_endpoints,
            )
        ),
        job.cancel_event,
        f"new-wine-flush-{job_id[:8]}",
    )
    return snapshot


async def start_slow_listening_job(
    spotify: Spotify, playlist_id: str, *, dry_run: bool
) -> BlastJobResult:
    """Start one Slow Listening web job, rejecting another playlist routine.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_slow_listening", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Slow Listening flush queued in dry-run mode."
            if dry_run
            else "Slow Listening flush queued.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        _run_slow_listening_job(job_id, spotify, playlist_id, dry_run),
        job.cancel_event,
        f"slow-listening-flush-{job_id[:8]}",
    )
    return snapshot


async def start_something_old_job(
    spotify: Spotify, playlist_id: str, api_key: str, username: str, *, dry_run: bool
) -> BlastJobResult:
    """Start one interactive Something Old job with reload-safe state.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        api_key: Configured Last.fm API credential.
        username: Configured Last.fm username.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="something_old", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Something Old queued in dry-run mode."
            if dry_run
            else "Something Old queued.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_something_old_job(
                job_id, spotify, playlist_id, api_key, username, dry_run
            )
        ),
        job.cancel_event,
        f"something-old-{job_id[:8]}",
    )
    return snapshot


async def start_release_check_job(
    spotify: Spotify,
    playlists: release_check.ReleaseCheckPlaylists,
    api_key: str,
    username: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one interactive release check with reload-safe web state.

    Args:
        spotify: Caller-owned Spotify client.
        playlists: Configured playlist identities.
        api_key: Configured Last.fm API credential.
        username: Configured Last.fm username.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="check_new_releases", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "New-release check queued in dry-run mode."
            if dry_run
            else "New-release check queued.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_release_check_job(
                job_id, spotify, playlists, api_key, username, dry_run
            )
        ),
        job.cancel_event,
        f"release-check-{job_id[:8]}",
    )
    return snapshot


async def start_discography_job(
    spotify: Spotify,
    playlist_ids: dict[discography.QueueName, str],
    queue_3_playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one interactive discography planner with reload-safe state.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_ids: Ordered playlist identities.
        queue_3_playlist_id: Configured queue 3 playlist identity.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="plan_discographies", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Discography planning queued in dry-run mode."
            if dry_run
            else "Discography planning queued.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_discography_job(
                job_id, spotify, playlist_ids, queue_3_playlist_id, dry_run
            )
        ),
        job.cancel_event,
        f"discography-plan-{job_id[:8]}",
    )
    return snapshot


async def start_requeue_for_a_dream_job(
    spotify: Spotify, playlist_id: str, *, dry_run: bool
) -> BlastJobResult:
    """Start one Requeue for a Dream job with reload-safe state.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        dry_run: Whether to preview without durable writes.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id, command="flush_requeue_for_a_dream", dry_run=dry_run
            )
        )
        _append_blast_log_locked(
            job,
            "Requeue for a Dream queued in dry-run mode."
            if dry_run
            else "Requeue for a Dream queued.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        _run_requeue_for_a_dream_job(job_id, spotify, playlist_id, dry_run),
        job.cancel_event,
        f"requeue-for-a-dream-{job_id[:8]}",
    )
    return snapshot


async def start_palace_of_memory_job(
    spotify: Spotify,
    playlist_id: str | None,
    *,
    dry_run: bool,
    alphabetical_start: str | None,
    cursor_position: int | None,
) -> BlastJobResult:
    """Start one reload-safe Palace fill or cursor adjustment.

    Args:
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        dry_run: Whether to preview without durable writes.
        alphabetical_start: Optional alphabetical cursor override.
        cursor_position: Optional explicit cursor position.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist routine is already running")
        job_id = uuid4().hex
        cursor_only = cursor_position is not None
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_palace_of_memory",
                dry_run=dry_run,
                palace_cursor_only=cursor_only,
                palace_alphabetical_reference=str(cursor_position)
                if cursor_only
                else alphabetical_start,
            )
        )
        queued_message = (
            f"Palace alphabetical cursor adjustment to {cursor_position} queued."
            if cursor_only
            else "Palace of Memory queued in dry-run mode."
            if dry_run
            else "Palace of Memory queued."
        )
        _append_blast_log_locked(job, queued_message)
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (
            _run_palace_of_memory_job(
                job_id,
                spotify,
                playlist_id,
                dry_run,
                alphabetical_start,
                cursor_position,
            )
        ),
        job.cancel_event,
        f"palace-of-memory-{job_id[:8]}",
    )
    return snapshot


async def start_scrobble_history_job(
    api_key: str, username: str, *, dry_run: bool, full_rebuild: bool = False
) -> BlastJobResult:
    """Start one shared Last.fm history refresh with reload-safe state.

    Args:
        api_key: Configured Last.fm API credential.
        username: Configured Last.fm username.
        dry_run: Whether to preview without durable writes.
        full_rebuild: Whether to discard prior incremental progress.

    Returns:
        Original operation result.
    """
    with _blast_jobs_lock:
        _require_playlist_slot("another playlist or history routine is running")
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="update_scrobble_history",
                dry_run=dry_run,
                history_full_rebuild=full_rebuild,
            )
        )
        _append_blast_log_locked(
            job,
            "Last.fm scrobble history update queued in dry-run mode."
            if dry_run
            else "Last.fm scrobble history update queued.",
        )
        register_job(_blast_jobs, job_id, job)
        snapshot = _blast_job_snapshot(job)
    current_execution().jobs.start(
        (_run_scrobble_history_job(job_id, api_key, username, dry_run, full_rebuild)),
        job.cancel_event,
        f"scrobble-history-{job_id[:8]}",
    )
    return snapshot


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Hydrate durable data once whenever an API process starts."""
    await _hydrate_library_data()
    async with ExecutionRuntime() as runtime:
        _app.state.execution = runtime
        yield


def _artist_not_found(request: Request, exc: ArtistNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def _ambiguous_artist(request: Request, exc: AmbiguousArtistError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


def _album_not_found(request: Request, exc: AlbumNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def _ambiguous_album(request: Request, exc: AmbiguousAlbumError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


def _track_not_found(request: Request, exc: TrackNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def _ambiguous_track(request: Request, exc: AmbiguousTrackError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


def _invalid_spotify_lookup(
    request: Request, exc: SpotifyLookupResponseError
) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


def _spotify_lookup_failed(request: Request, exc: SpotifyException) -> JSONResponse:
    """Return useful lookup errors instead of an opaque HTTP 500 response."""
    if exc.http_status == 429:
        retry_after = review_album_limits.get_retry_after_seconds(exc)
        detail = (
            "Spotify rate limit reached after trying all configured credentials. "
            f"{review_album_limits.format_retry_after(retry_after)}."
        )
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        return JSONResponse(
            status_code=429, content={"detail": detail}, headers=headers
        )
    status_code = exc.http_status if exc.http_status in {400, 403, 404} else 502
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": (
                f"Spotify request failed (HTTP {exc.http_status}): "
                f"{exc.msg or 'unknown Spotify error'}"
            )
        },
    )


def _configured_queue_playlists() -> the_queue.QueuePlaylists:
    """Parse every playlist shared by Queue fill and flush operations."""
    configuration = Settings()
    try:
        return the_queue.QueuePlaylists.from_references(
            configuration.the_queue_playlist,
            configuration.the_queue_2_playlist,
            configuration.new_kids_on_the_block_playlist,
            configuration.the_queue_3_playlist,
            configuration.unlucky_ones_playlist,
        )
    except the_queue.QueueConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _cancel_queue_job(job_id: str, command: str, label: str) -> BlastJobResult:
    """Signal one active Queue fill or flush worker to stop cleanly."""
    job = get_blast_job(job_id, command=command)
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail=f"{label} job is not active")
        job.result.status = "cancelling"
        job.result.queue_pending_choice = None
        job.result.detail = f"Stopping {label}"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


def _configured_album_discovery_playlists() -> tuple[str, str, str, str, str]:
    """Load the five shared New Kids and Queue 2 playlist settings."""
    configuration = Settings()
    try:
        new_kids_playlist_id = new_kids.parse_playlist_id(
            configuration.new_kids_on_the_block_playlist,
            "NEW_KIDS_ON_THE_BLOCK_PLAYLIST",
        )
        queue_2_playlist_id = new_kids.parse_playlist_id(
            configuration.the_queue_2_playlist, "THE_QUEUE_2_PLAYLIST"
        )
        great_discoveries_playlist_id = new_kids.parse_playlist_id(
            configuration.great_discoveries_2026_playlist,
            "GREAT_DISCOVERIES_2026_PLAYLIST",
        )
        unlucky_ones_playlist_id = new_kids.parse_playlist_id(
            configuration.unlucky_ones_playlist, "UNLUCKY_ONES_PLAYLIST"
        )
        newfoundland_playlist_id = new_kids.parse_playlist_id(
            configuration.discography_newfoundland_playlist,
            "DISCOGRAPHY_NEWFOUNDLAND_PLAYLIST",
        )
    except new_kids.NewKidsConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return (
        new_kids_playlist_id,
        queue_2_playlist_id,
        great_discoveries_playlist_id,
        unlucky_ones_playlist_id,
        newfoundland_playlist_id,
    )


def _server_file_status(path: Path) -> ServerFileStatus:
    """Return a UTC modification timestamp without failing on a missing file."""
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    except FileNotFoundError:
        return ServerFileStatus(filename=path.name, exists=False)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not read server file status for {path.name}.",
        ) from exc
    return ServerFileStatus(filename=path.name, exists=True, updated_at=modified_at)


async def _run_new_year_job(
    job_id: str, spotify: Spotify, year: int | None, dry_run: bool
) -> None:
    """Run the annual workflow through the shared routine and job registry."""
    await NewYearWorker(
        job_id=job_id,
        spotify=spotify,
        year=year,
        dry_run=dry_run,
        context=_playlist_context(),
    ).run()


def _active_playlist_jobs(command: str) -> list[BlastJobResult]:
    with _blast_jobs_lock:
        return active_playlist_snapshots(_blast_jobs.values(), command)


def _active_analysis_jobs() -> list[AnalysisJobResult]:
    with _analysis_jobs_lock:
        return active_analysis_snapshots(_analysis_jobs.values())


def _analysis_resources(
    resources: tuple[str, ...],
) -> dict[str, AnalysisResourceProgress]:
    progress = {}
    for resource in resources:
        progress[resource] = AnalysisResourceProgress()
    return progress


async def _hydrate_library_data() -> None:
    async with blocking_capacity():
        task = asyncio.create_task(asyncio.to_thread(hydrate_runtime_library_data))
        await finish_blocking(task)
