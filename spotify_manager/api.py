"""FastAPI interface exposing the same logic as the Typer CLI.

Run with::

    uvicorn spotify_manager.api:app --reload

or via the installed script ``spotify-api``.

Artist stats and album evaluation use live Spotify state. Library analyses run
as cancellable background jobs with pollable progress. The parsed export used
by legacy endpoints is cached; call ``POST /library/refresh`` after replacing
``YourLibrary.json``.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from threading import Event
from threading import Lock
from threading import Thread
from typing import Annotated
from typing import Literal
from uuid import uuid4

from fastapi import Depends
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pydantic import Field
from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import AmbiguousArtistError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import SpotifyLookupResponseError
from spotify_manager.processors.library_lookups import evaluate_album_live
from spotify_manager.processors.library_lookups import get_live_artist_library_stats
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.routines import analyse_library as library_analysis
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import daily_mind_radio
from spotify_manager.routines import found_art
from spotify_manager.routines import new_wine
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import requeue_for_a_dream
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import something_old
from spotify_manager.routines.convert_library_file import analyse_comparison
from spotify_manager.routines.convert_library_file import (
    compare_your_library_and_all_albums,
)
from spotify_manager.routines.convert_library_file import convert_your_library_file
from spotify_manager.routines.convert_library_file import restore_your_library_from_file
from spotify_manager.routines.count_items import count_artists_in_library
from spotify_manager.routines.monthly_routine import run_monthly_routines
from spotify_manager.settings import Settings


class CommandResult(BaseModel):
    """Result of running a side-effecting command endpoint."""

    command: str
    status: str = "completed"
    detail: str | None = None


class CountResult(BaseModel):
    """Number of artists in the YourLibrary file."""

    count: int


JobStatus = Literal[
    "queued",
    "running",
    "waiting",
    "cancelling",
    "cancelled",
    "paused",
    "completed",
    "failed",
]


class AnalysisResourceProgress(BaseModel):
    """Latest progress for one library resource."""

    completed: int = 0
    total: int | None = None
    status: str = "Queued"


class AnalysisJobLog(BaseModel):
    """One timestamped analysis event shown by the web interface."""

    sequence: int
    timestamp: str
    message: str


class AnalysisJobResult(BaseModel):
    """Pollable state for one background library analysis."""

    job_id: str
    command: str
    status: JobStatus = "queued"
    detail: str | None = None
    retry_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    run_id: str | None = None
    backup_dir: str | None = None
    full_rebuild: bool = False
    resources: dict[str, AnalysisResourceProgress]
    logs: list[AnalysisJobLog] = Field(default_factory=list)


class ServerFileStatus(BaseModel):
    """Filesystem update status for one canonical server-side mirror."""

    filename: str
    exists: bool
    updated_at: str | None = None


class LibraryMirrorFilesStatus(BaseModel):
    """Update status for the files consumed by New Wine."""

    files: list[ServerFileStatus]


class BlastSelectionResult(BaseModel):
    """One Last.fm selection and its Spotify playlist outcome."""

    selected_date: str
    page: int
    total_pages: int
    direction: str
    position: int
    lastfm_scrobble: str
    spotify_match: str | None = None
    liked: bool | None = None
    track_similarity: float | None = None
    album_similarity: float | None = None
    qualifying_matches: int = 0
    action: str


class FoundArtSelectionResult(BaseModel):
    """One Last.fm recommendation and its Spotify playlist outcome."""

    artist: str
    track: str
    score: float
    best_match: float
    supporting_seeds: list[str] = Field(default_factory=list)
    base_rank: int
    weekly_rank: float
    spotify_match: str | None = None
    track_similarity: float | None = None
    action: str


class PalaceAlbumSelectionResult(BaseModel):
    """One Palace of Memory album and its resolved first track."""

    source: str
    selected_date: str | None = None
    history_position: int | None = None
    albums_on_date: int | None = None
    artist: str
    album: str
    spotify_album: str | None = None
    first_track: str | None = None
    action: str


class PalaceAlbumRefreshResult(BaseModel):
    """Saved-album mirror refresh details shown by the web client."""

    previous: int
    current: int
    added: int
    removed: int
    skipped: int
    persisted: bool
    backup_path: str | None = None


class NewWineReleaseOption(BaseModel):
    """One release offered while a web flush waits for a choice."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    primary_artist_name: str


class NewWinePendingChoice(BaseModel):
    """Current interactive choice exposed to the web client."""

    artist: str
    source_track: str
    terminal_release: bool = False
    releases: list[NewWineReleaseOption] = Field(default_factory=list)


class NewWineTrackResult(BaseModel):
    """One completed New Wine source-track decision."""

    artist: str
    source_track: str
    release: str
    release_type: str
    current_liked: bool
    consecutive_unliked: int
    action: str
    target_track: str | None = None
    album_unsaved: bool = False
    advance_reason: str | None = None
    drop_reason: str | None = None
    continuation_release: str | None = None
    continuation_track: str | None = None


class NewWineCellarTrackResult(BaseModel):
    """One Wine Cellar entry moved or reconciled by a web flush."""

    artist: str
    source_track: str
    action: str
    liked_tracks: int | None = None
    saved_albums: int | None = None


class NewWineRefillResult(BaseModel):
    """Web representation of the post-flush Wine Cellar refill."""

    target_size: int
    before: int
    after: int
    added: int
    removed_from_cellar: int
    ineligible: int
    no_discovery: bool
    results: list[NewWineCellarTrackResult] = Field(default_factory=list)


class NewWineChoiceRequest(BaseModel):
    """Choice submitted for a waiting New Wine job."""

    choice: str


class SlowListeningReleaseOption(BaseModel):
    """One equal-date release offered for chronological ordering."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    plain: bool


class SlowListeningPendingChoice(BaseModel):
    """Current Slow Listening interaction exposed to the web client."""

    kind: Literal["track", "release_order", "completion"]
    artist: str
    source_track: str | None = None
    source_release: str | None = None
    target_track: str | None = None
    target_release: str | None = None
    release_date: str | None = None
    releases: list[SlowListeningReleaseOption] = Field(default_factory=list)


class SlowListeningTrackResult(BaseModel):
    """One completed Slow Listening source-track transition."""

    artist: str
    source_track: str
    source_release: str
    action: str
    target_track: str | None = None
    target_release: str | None = None
    skipped_candidates: list[str] = Field(default_factory=list)
    reason: str | None = None


class SlowListeningChoiceRequest(BaseModel):
    """Choice or release ordering submitted to a waiting web job."""

    choice: str
    order: list[str] = Field(default_factory=list)


class SomethingOldArtistOption(BaseModel):
    """One exact-name Spotify artist offered to the web client."""

    spotify_id: str
    name: str
    popularity: int | None = None
    followers: int | None = None


class SomethingOldReleaseOption(BaseModel):
    """One filtered studio album or EP offered for Something Old."""

    spotify_id: str
    name: str
    release_type: str
    release_date: str
    total_tracks: int
    saved: bool
    plain: bool


class SomethingOldPendingChoice(BaseModel):
    """Current Something Old interaction exposed to the web client."""

    kind: Literal["artist", "mode", "album"]
    artist: str
    scrobbles: int
    average_scrobble_date: str
    spotify_artist: str | None = None
    artist_candidates: list[SomethingOldArtistOption] = Field(default_factory=list)
    releases: list[SomethingOldReleaseOption] = Field(default_factory=list)


class SomethingOldRankingEntry(BaseModel):
    """One Golden Oldies artist shown in the web ranking preview."""

    artist: str
    scrobbles: int
    average_scrobble_date: str


class SomethingOldTrackResult(BaseModel):
    """One Spotify track selected for Something Old."""

    spotify_id: str
    track: str
    album: str
    artists: list[str]
    source: str
    lastfm_scrobbles: int | None = None


class SomethingOldChoiceRequest(BaseModel):
    """One artist, source mode, album, or quit choice."""

    choice: str


class BlastJobResult(BaseModel):
    """Pollable state for one Last.fm-based playlist job."""

    job_id: str
    command: str = "blast_from_the_past"
    status: JobStatus = "queued"
    detail: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    requested_count: int | None = None
    playlist_length_before: int | None = None
    playlist_length_after: int | None = None
    added: int | None = None
    random_org_timestamp: str | None = None
    target_dates: list[str] = Field(default_factory=list)
    missing_dates: list[str] = Field(default_factory=list)
    selections: list[BlastSelectionResult] = Field(default_factory=list)
    week_start: str | None = None
    history_tracks: int | None = None
    history_scrobbles: int | None = None
    history_export_scrobbles: int | None = None
    history_legacy_scrobbles_added: int | None = None
    live_scrobbles_added: int | None = None
    history_persisted: bool | None = None
    history_backup_path: str | None = None
    candidate_count: int | None = None
    found_art_results: list[FoundArtSelectionResult] = Field(default_factory=list)
    dry_run: bool = False
    no_discovery: bool = False
    processed: int | None = None
    total: int | None = None
    advanced: int | None = None
    dropped: int | None = None
    sent_to_sauvignon: int | None = None
    completed_singles: int | None = None
    skipped: int | None = None
    albums_unsaved: int | None = None
    new_wine_results: list[NewWineTrackResult] = Field(default_factory=list)
    new_wine_refill: NewWineRefillResult | None = None
    pending_choice: NewWinePendingChoice | None = None
    completed_artists: int | None = None
    slow_listening_results: list[SlowListeningTrackResult] = Field(default_factory=list)
    slow_listening_pending_choice: SlowListeningPendingChoice | None = None
    something_old_action: str | None = None
    something_old_artist: str | None = None
    something_old_average_scrobble_date: str | None = None
    something_old_spotify_artist: str | None = None
    something_old_mode: str | None = None
    something_old_release: str | None = None
    something_old_ranking: list[SomethingOldRankingEntry] = Field(default_factory=list)
    something_old_tracks: list[SomethingOldTrackResult] = Field(default_factory=list)
    something_old_pending_choice: SomethingOldPendingChoice | None = None
    requeue_action: str | None = None
    requeue_artist: str | None = None
    requeue_source_track: str | None = None
    requeue_source_release: str | None = None
    requeue_target_track: str | None = None
    requeue_target_release: str | None = None
    requeue_target_release_type: str | None = None
    requeue_target_release_date: str | None = None
    requeue_target_already_present: bool | None = None
    palace_cursor_only: bool = False
    palace_alphabetical_reference: str | None = None
    palace_alphabetical_start_index: int | None = None
    palace_alphabetical_next_index: int | None = None
    palace_alphabetical_cursor_overridden: bool = False
    palace_next_album_artist: str | None = None
    palace_next_album: str | None = None
    palace_cutoff_date: str | None = None
    palace_available_dates: int | None = None
    palace_album_refresh: PalaceAlbumRefreshResult | None = None
    palace_results: list[PalaceAlbumSelectionResult] = Field(default_factory=list)
    retry_at: str | None = None
    logs: list[AnalysisJobLog] = Field(default_factory=list)


@dataclass
class _AnalysisJob:
    """Mutable server-side state and cancellation signal for one job."""

    result: AnalysisJobResult
    cancel_event: Event
    next_log_sequence: int = 1


@dataclass
class _BlastJob:
    """Mutable server-side state for one playlist routine job."""

    result: BlastJobResult
    next_log_sequence: int = 1
    choice_event: Event = dataclass_field(default_factory=Event)
    cancel_event: Event = dataclass_field(default_factory=Event)
    submitted_choice: str | None = None
    submitted_order: tuple[str, ...] | None = None


class _NewWineJobCancelledError(RuntimeError):
    """Stop one web flush while preserving the routine's durable state."""


class _SlowListeningJobCancelledError(RuntimeError):
    """Stop one Slow Listening web flush at an interaction boundary."""


class _SomethingOldJobCancelledError(RuntimeError):
    """Stop one Something Old web job at an interaction or retry boundary."""


class _RequeueForADreamJobCancelledError(RuntimeError):
    """Stop one Requeue for a Dream job at an API or retry boundary."""


class _PalaceOfMemoryJobCancelledError(RuntimeError):
    """Stop one Palace of Memory job at an API or retry boundary."""


_analysis_jobs: dict[str, _AnalysisJob] = {}
_analysis_jobs_lock = Lock()
_ACTIVE_JOB_STATUSES = {"queued", "running", "waiting", "cancelling"}
_MAX_ANALYSIS_LOGS = 250
_analysis_logger = logging.getLogger(__name__)
_blast_jobs: dict[str, _BlastJob] = {}
_blast_jobs_lock = Lock()
_MAX_BLAST_LOGS = 250
LIBRARY_MIRROR_FILE_PATHS = (
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.albums_total,
    library_analysis.DEFAULT_LIVE_MIRROR_PATHS.liked_tracks_total,
)
SPOTIFY_CONNECTION_FAILURE_DETAIL = (
    "Spotify connection remained unavailable after automatic retries. "
    "Please try again shortly."
)


@lru_cache
def get_client() -> Spotify:
    """Provide a cached spotipy client (overridable in tests)."""
    return get_spotipy_client(allow_interactive_auth=False)


@lru_cache
def get_analysis_client() -> Spotify:
    """Provide a client whose retries are controlled by the analysis routine."""
    return get_spotipy_client(
        retries=0,
        status_retries=0,
        status_forcelist=(999,),
        allow_interactive_auth=False,
    )


@lru_cache
def get_interactive_client() -> Spotify:
    """Provide an isolated no-retry client for interactive web routines."""
    return get_spotipy_client(
        retries=0,
        status_retries=0,
        status_forcelist=(999,),
        allow_interactive_auth=False,
    )


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
    job.result.logs.append(
        AnalysisJobLog(
            sequence=job.next_log_sequence,
            timestamp=datetime.now(UTC).isoformat(),
            message=message,
        )
    )
    job.next_log_sequence += 1
    if len(job.result.logs) > _MAX_ANALYSIS_LOGS:
        del job.result.logs[: len(job.result.logs) - _MAX_ANALYSIS_LOGS]


def _blast_job_snapshot(job: _BlastJob) -> BlastJobResult:
    """Return an isolated response model for one mutable playlist job."""
    return job.result.model_copy(deep=True)


def _append_blast_log_locked(job: _BlastJob, message: str) -> None:
    """Append one bounded playlist-job log entry while holding its lock."""
    if not message:
        return
    job.result.logs.append(
        AnalysisJobLog(
            sequence=job.next_log_sequence,
            timestamp=datetime.now(UTC).isoformat(),
            message=message,
        )
    )
    job.next_log_sequence += 1
    if len(job.result.logs) > _MAX_BLAST_LOGS:
        del job.result.logs[: len(job.result.logs) - _MAX_BLAST_LOGS]


def get_analysis_job(job_id: str) -> _AnalysisJob:
    """Return one job or raise a conventional API 404."""
    with _analysis_jobs_lock:
        job = _analysis_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="analysis job not found")
    return job


def get_blast_job(job_id: str, command: str | None = None) -> _BlastJob:
    """Return one playlist job or raise a conventional API 404."""
    with _blast_jobs_lock:
        job = _blast_jobs.get(job_id)
    if job is None or (command is not None and job.result.command != command):
        raise HTTPException(status_code=404, detail="playlist job not found")
    return job


def _run_analysis_job(
    job_id: str,
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None,
    full_rebuild: bool = False,
) -> None:
    """Execute one analysis worker and translate outcomes into job state."""
    job = get_analysis_job(job_id)
    with _analysis_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Analysis started"
        _append_job_log_locked(job, f"{mode.title()} analysis started.")

    def progress_callback(
        resource: library_analysis.ResourceName,
        completed: int,
        total: int | None,
        progress_status: str,
    ) -> None:
        with _analysis_jobs_lock:
            progress = job.result.resources[resource]
            status_changed = progress.status != progress_status
            progress.completed = completed
            progress.total = total
            progress.status = progress_status
            if job.result.status != "cancelling":
                job.result.status = "running"
                job.result.detail = f"{resource.title()}: {progress_status}"
            if status_changed:
                count = str(completed)
                if total is not None:
                    count = f"{completed} / {max(completed, total)}"
                _append_job_log_locked(
                    job,
                    f"{resource.title()}: {progress_status} ({count}).",
                )

    def echo(line: str) -> None:
        with _analysis_jobs_lock:
            _append_job_log_locked(job, line)
            if job.result.status not in {"waiting", "cancelling"}:
                job.result.detail = line

    def retry_wait(notice: library_analysis.RetryNotice) -> bool:
        retry_at = datetime.now(UTC) + timedelta(seconds=notice.delay_seconds)
        failure = (
            f"Spotify HTTP {notice.http_status}"
            if notice.http_status is not None
            else "Spotify connection interrupted"
        )
        with _analysis_jobs_lock:
            job.result.status = "waiting"
            job.result.retry_at = retry_at.isoformat()
            job.result.detail = (
                f"{failure}; retry {notice.attempt} while {notice.operation}"
            )
            _append_job_log_locked(
                job,
                f"Waiting until {retry_at.isoformat()} before retry "
                f"{notice.attempt} after {failure} "
                f"while {notice.operation}. Cancel to save and stop.",
            )
        cancelled = job.cancel_event.wait(notice.delay_seconds)
        with _analysis_jobs_lock:
            job.result.retry_at = None
            if not cancelled:
                job.result.status = "running"
                job.result.detail = "Retrying Spotify request"
                _append_job_log_locked(job, "Retrying Spotify request now.")
        return not cancelled

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        if mode == "async":
            summary = library_analysis.analyse_library_async_routine(
                echo=echo,
                progress_callback=progress_callback,
                cancel_check=job.cancel_event.is_set,
            )
        elif mode == "sync":
            if spotify is None:
                raise library_analysis.LibrarySyncError(
                    "A Spotify client is required for live analysis."
                )
            summary = library_analysis.analyse_library_sync_routine(
                spotify,
                echo=echo,
                progress_callback=progress_callback,
                retry_wait=retry_wait,
                cancel_check=job.cancel_event.is_set,
            )
        else:
            if spotify is None:
                raise library_analysis.LibrarySyncError(
                    "A Spotify client is required for live mirror refresh."
                )
            summary = library_analysis.refresh_live_library_mirrors_routine(
                spotify,
                echo=echo,
                progress_callback=progress_callback,
                retry_wait=retry_wait,
                cancel_check=job.cancel_event.is_set,
                full_rebuild=full_rebuild,
            )
    except library_analysis.LibraryAnalysisCancelledError as exc:
        with _analysis_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = f"{exc} Progress was saved."
            _append_job_log_locked(job, job.result.detail)
    except library_analysis.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _analysis_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = "Spotify rate limit reached. Progress was saved."
            _append_job_log_locked(job, job.result.detail)
    except library_analysis.LibrarySyncError as exc:
        with _analysis_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_job_log_locked(job, f"Analysis failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected library analysis error")
        with _analysis_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected analysis error: {exc}"
            _append_job_log_locked(job, job.result.detail)
    else:
        with _analysis_jobs_lock:
            job.result.status = "completed"
            job.result.detail = "Analysis completed"
            job.result.run_id = summary.run_id
            job.result.backup_dir = summary.backup_dir
            for resource in summary.resources:
                _append_job_log_locked(
                    job,
                    f"{resource.resource.title()}: {resource.previous} -> "
                    f"{resource.current} (+{resource.added}, "
                    f"-{resource.removed}, skipped {resource.skipped}).",
                )
            _append_job_log_locked(
                job,
                f"Analysis completed. Run {summary.run_id}; "
                f"backup {summary.backup_dir}.",
            )
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _analysis_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def start_analysis_job(
    mode: library_analysis.AnalysisMode,
    spotify: Spotify | None = None,
    full_rebuild: bool = False,
) -> AnalysisJobResult:
    """Start one background analysis, rejecting duplicate active modes."""
    command = (
        "refresh_library_mirrors" if mode == "mirrors" else f"analyse_library_{mode}"
    )
    with _analysis_jobs_lock:
        for existing in _analysis_jobs.values():
            if (
                existing.result.command == command
                and existing.result.status in _ACTIVE_JOB_STATUSES
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "an analysis of this type is already running",
                        "job_id": existing.result.job_id,
                    },
                )
        job_id = uuid4().hex
        job = _AnalysisJob(
            result=AnalysisJobResult(
                job_id=job_id,
                command=command,
                full_rebuild=full_rebuild if mode == "mirrors" else False,
                resources={
                    resource: AnalysisResourceProgress()
                    for resource in (
                        ("albums", "tracks")
                        if mode == "mirrors"
                        else ("albums", "tracks", "artists")
                    )
                },
            ),
            cancel_event=Event(),
        )
        _append_job_log_locked(job, f"{mode.title()} analysis queued.")
        _analysis_jobs[job_id] = job
        snapshot = _job_snapshot(job)

    Thread(
        target=_run_analysis_job,
        args=(job_id, mode, spotify, full_rebuild),
        name=f"library-analysis-{mode}-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def _blast_selection_result(
    result: blast_from_past.SpotifySelectionResult,
) -> BlastSelectionResult:
    """Convert one routine result into its stable API representation."""
    selection = result.selection
    scrobble = selection.scrobble
    lastfm_album = scrobble.album or "(no album)"
    spotify_match = None
    liked = None
    track_similarity = None
    album_similarity = None
    if result.match is not None:
        spotify_album = result.match.album or "(no album)"
        spotify_match = (
            f"{', '.join(result.match.artists)} - {result.match.track} - "
            f"{spotify_album}"
        )
        liked = result.match.liked
        track_similarity = result.match.track_similarity
        album_similarity = result.match.album_similarity
    return BlastSelectionResult(
        selected_date=selection.selected_date.isoformat(),
        page=selection.page,
        total_pages=selection.total_pages,
        direction=selection.direction,
        position=selection.position,
        lastfm_scrobble=f"{scrobble.artist} - {scrobble.track} - {lastfm_album}",
        spotify_match=spotify_match,
        liked=liked,
        track_similarity=track_similarity,
        album_similarity=album_similarity,
        qualifying_matches=result.qualifying_matches,
        action=result.action,
    )


def _run_blast_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
) -> None:
    """Execute one web playlist job and retain progress, logs, and results."""
    job = get_blast_job(job_id)
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Playlist routine started"
        _append_blast_log_locked(job, "A blast from the past started.")

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = blast_from_past.add_blast_from_past_to_spotify(
            spotify,
            playlist_id,
            count=count,
            max_playlist_length=max_playlist_length,
            progress_callback=echo,
        )
    except (blast_from_past.BlastFromPastError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Playlist routine failed: {exc}")
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected blast-from-the-past error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected playlist error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        selections = [_blast_selection_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requested_count = summary.requested_count
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.added
            job.result.selections = selections
            if summary.batch is not None:
                job.result.random_org_timestamp = summary.batch.generated_at.isoformat()
            job.result.detail = (
                f"Added {summary.added} of {summary.requested_count} selections; "
                f"playlist {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for selection in selections:
                target = selection.spotify_match or "no qualifying Spotify match"
                liked_label = " liked" if selection.liked else ""
                _append_blast_log_locked(
                    job,
                    f"{selection.selected_date}: {selection.lastfm_scrobble} -> "
                    f"{target} ({selection.action}{liked_label}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_daily_mind_radio_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
) -> None:
    """Execute one Daily Mind Radio web job and retain its complete trace."""
    job = get_blast_job(job_id, command="daily_mind_radio")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Playlist routine started"
        _append_blast_log_locked(job, "Daily Mind Radio started.")

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = daily_mind_radio.add_daily_mind_radio_to_spotify(
            spotify,
            playlist_id,
            progress_callback=echo,
        )
    except (blast_from_past.BlastFromPastError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Playlist routine failed: {exc}")
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Daily Mind Radio error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected playlist error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        selections = [_blast_selection_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requested_count = len(summary.batch.selections)
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.added
            job.result.target_dates = [
                target_date.isoformat() for target_date in summary.batch.target_dates
            ]
            job.result.missing_dates = [
                missing_date.isoformat() for missing_date in summary.batch.missing_dates
            ]
            job.result.selections = selections
            if summary.batch.generated_at is not None:
                job.result.random_org_timestamp = summary.batch.generated_at.isoformat()
            if summary.playlist_length_before is None:
                job.result.detail = (
                    "No anniversary dates had scrobbles; nothing was added."
                )
            else:
                job.result.detail = (
                    f"Added {summary.added} of {len(summary.batch.selections)} "
                    f"populated dates; playlist {summary.playlist_length_before} -> "
                    f"{summary.playlist_length_after}."
                )
            for selection in selections:
                target = selection.spotify_match or "no qualifying Spotify match"
                liked_label = " liked" if selection.liked else ""
                _append_blast_log_locked(
                    job,
                    f"{selection.selected_date}: {selection.lastfm_scrobble} -> "
                    f"{target} ({selection.action}{liked_label}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _found_art_selection_result(
    result: found_art.FoundArtResult,
) -> FoundArtSelectionResult:
    """Convert one Found Art result into its stable API representation."""
    spotify_match = None
    track_similarity = None
    if result.match is not None:
        album = result.match.album or "(no album)"
        spotify_match = (
            f"{', '.join(result.match.artists)} - {result.match.track} - {album}"
        )
        track_similarity = result.match.track_similarity
    return FoundArtSelectionResult(
        artist=result.candidate.artist,
        track=result.candidate.track,
        score=result.candidate.score,
        best_match=result.candidate.best_match,
        supporting_seeds=list(result.candidate.supporting_seeds),
        base_rank=result.candidate.base_rank,
        weekly_rank=result.candidate.weekly_rank,
        spotify_match=spotify_match,
        track_similarity=track_similarity,
        action=result.action,
    )


def _run_found_art_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int,
) -> None:
    """Execute one Found Art web job and retain its complete trace."""
    job = get_blast_job(job_id, command="found_art")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Found Art started"
        _append_blast_log_locked(job, "Found Art started.")

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)
    lastfm = LastFmClient(
        api_key,
        username,
        event_callback=echo,
    )

    try:
        summary = found_art.run_found_art(
            spotify,
            lastfm,
            playlist_id,
            count=count,
            progress_callback=echo,
        )
    except (found_art.FoundArtError, LastFmError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Found Art failed: {exc}")
    except RequestException:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = SPOTIFY_CONNECTION_FAILURE_DETAIL
            _append_blast_log_locked(job, job.result.detail)
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Found Art error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Found Art error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_found_art_selection_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requested_count = summary.requested_count
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = summary.added
            job.result.week_start = summary.week_start.isoformat()
            job.result.history_tracks = summary.history_tracks
            job.result.history_scrobbles = summary.history_scrobbles
            job.result.live_scrobbles_added = summary.live_scrobbles_added
            job.result.candidate_count = summary.candidate_count
            job.result.found_art_results = results
            job.result.detail = (
                f"Added {summary.added} of {summary.requested_count} "
                f"recommendations; playlist {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                target = result.spotify_match or "no unliked qualifying match"
                _append_blast_log_locked(
                    job,
                    f"{result.artist} - {result.track} -> {target} ({result.action}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _new_wine_track_result(result: new_wine.FlushResult) -> NewWineTrackResult:
    """Convert one New Wine result into its stable API representation."""
    return NewWineTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        release=result.release,
        release_type=result.release_type,
        current_liked=result.current_liked,
        consecutive_unliked=result.consecutive_unliked,
        action=result.action,
        target_track=result.target_track,
        album_unsaved=result.album_unsaved,
        advance_reason=result.advance_reason,
        drop_reason=result.drop_reason,
        continuation_release=result.continuation_release,
        continuation_track=result.continuation_track,
    )


def _new_wine_refill_result(
    refill: new_wine.CellarRefillSummary | None,
) -> NewWineRefillResult | None:
    """Convert a Wine Cellar refill while keeping web payloads compact."""
    if refill is None:
        return None
    return NewWineRefillResult(
        target_size=refill.target_size,
        before=refill.before,
        after=refill.after,
        added=refill.added,
        removed_from_cellar=refill.removed_from_cellar,
        ineligible=refill.ineligible,
        no_discovery=refill.no_discovery,
        results=[
            NewWineCellarTrackResult(
                artist=result.artist,
                source_track=result.source_track,
                action=result.action,
                liked_tracks=result.liked_tracks,
                saved_albums=result.saved_albums,
            )
            for result in refill.results
            if result.action != "ineligible"
        ],
    )


def _run_new_wine_job(
    job_id: str,
    spotify: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    wine_cellar_playlist_id: str,
    dry_run: bool,
    no_discovery: bool,
) -> None:
    """Execute one interactive New Wine flush as a reconnectable web job."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "New Wine flush started"
        _append_blast_log_locked(
            job,
            f"New Wine flush started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        if job.cancel_event.is_set():
            raise _NewWineJobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = progress_status

    def choice_reader(
        source: new_wine.PlaylistTrack,
        candidates: tuple[new_wine.ReleaseCandidate, ...],
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _NewWineJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.pending_choice = NewWinePendingChoice(
                artist=source.primary_artist_name,
                source_track=source.name,
                terminal_release=source.release.release_type in {"Album", "EP"},
                releases=[
                    NewWineReleaseOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        release_type=candidate.release_type,
                        release_date=candidate.release_date,
                        total_tracks=candidate.total_tracks,
                        primary_artist_name=candidate.primary_artist_name,
                    )
                    for candidate in candidates
                ],
            )
            job.result.status = "waiting"
            job.result.detail = (
                f"Choose a release for {source.primary_artist_name} after {source.name}"
            )
            _append_blast_log_locked(job, job.result.detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _NewWineJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying release choice"
                _append_blast_log_locked(job, f"Release choice received: {choice}.")
                return choice

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _NewWineJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = new_wine.flush_new_wine(
            spotify,
            new_wine_playlist_id,
            sauvignon_playlist_id,
            choice_reader=choice_reader,
            wine_cellar_playlist_id=wine_cellar_playlist_id,
            no_discovery=no_discovery,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _NewWineJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.pending_choice = None
            job.result.detail = (
                "New Wine flush stopped. Progress was saved."
                if not dry_run
                else "New Wine dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.pending_choice = None
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.pending_choice = None
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + ". "
                "Progress was saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except (new_wine.NewWineError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.pending_choice = None
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"New Wine flush failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected New Wine flush error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.pending_choice = None
            job.result.detail = f"Unexpected New Wine error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_new_wine_track_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.processed = summary.processed
            job.result.total = summary.total
            job.result.advanced = summary.advanced
            job.result.dropped = summary.dropped
            job.result.sent_to_sauvignon = summary.sent_to_sauvignon
            job.result.completed_singles = summary.completed_singles
            job.result.skipped = summary.skipped
            job.result.albums_unsaved = summary.albums_unsaved
            job.result.new_wine_results = results
            job.result.new_wine_refill = _new_wine_refill_result(summary.refill)
            job.result.pending_choice = None
            if summary.paused:
                job.result.detail = "New Wine flush paused. Progress was saved."
            else:
                unsave_label = "to unsave" if dry_run else "unsaved"
                job.result.detail = (
                    f"{summary.processed}/{summary.total} processed; "
                    f"{summary.advanced} advanced, {summary.dropped} dropped, "
                    f"{summary.sent_to_sauvignon} sent to Sauvignon, "
                    f"{summary.albums_unsaved} albums {unsave_label}."
                )
                if summary.refill is not None:
                    job.result.detail += (
                        f" New Wine {summary.refill.before} -> "
                        f"{summary.refill.after}; {summary.refill.added} pulled "
                        "from Wine Cellar."
                    )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _slow_listening_track_result(
    result: slow_listening.FlushResult,
) -> SlowListeningTrackResult:
    """Convert one Slow Listening result into its stable API representation."""
    return SlowListeningTrackResult(
        artist=result.artist,
        source_track=result.source_track,
        source_release=result.source_release,
        action=result.action,
        target_track=result.target_track,
        target_release=result.target_release,
        skipped_candidates=list(result.skipped_candidates),
        reason=result.reason,
    )


def _run_slow_listening_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute an interactive Slow Listening flush as a reconnectable job."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Slow Listening flush started"
        _append_blast_log_locked(
            job,
            f"Slow Listening flush started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def progress_callback(completed: int, total: int, progress_status: str) -> None:
        if job.cancel_event.is_set():
            raise _SlowListeningJobCancelledError
        with _blast_jobs_lock:
            job.result.processed = completed
            job.result.total = total
            job.result.detail = progress_status

    def wait_for_submission(
        pending: SlowListeningPendingChoice,
        detail: str,
    ) -> tuple[str, tuple[str, ...] | None]:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _SlowListeningJobCancelledError
            job.submitted_choice = None
            job.submitted_order = None
            job.choice_event.clear()
            job.result.slow_listening_pending_choice = pending
            job.result.status = "waiting"
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _SlowListeningJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                order = job.submitted_order
                job.submitted_choice = None
                job.submitted_order = None
                job.choice_event.clear()
                job.result.slow_listening_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying Slow Listening choice"
                _append_blast_log_locked(
                    job,
                    f"Slow Listening choice received: {choice}.",
                )
                return choice, order

    def action_reader(
        source: new_wine.PlaylistTrack,
        target: new_wine.ReleaseTrack,
        target_release: slow_listening.DiscographyRelease,
    ) -> str:
        choice, _order = wait_for_submission(
            SlowListeningPendingChoice(
                kind="track",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
                target_track=target.name,
                target_release=target_release.name,
            ),
            (
                f"Add {target.name} ({target_release.name}) after "
                f"{source.primary_artist_name} - {source.name}?"
            ),
        )
        return choice

    def order_reader(
        release_date: str,
        candidates: tuple[slow_listening.DiscographyRelease, ...],
    ) -> tuple[str, ...]:
        artist = candidates[0].primary_artist_name if candidates else "Artist"
        choice, order = wait_for_submission(
            SlowListeningPendingChoice(
                kind="release_order",
                artist=artist,
                release_date=release_date,
                releases=[
                    SlowListeningReleaseOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        release_type=candidate.release_type,
                        release_date=candidate.release_date,
                        total_tracks=candidate.total_tracks,
                        saved=candidate.saved,
                        plain=candidate.plain,
                    )
                    for candidate in candidates
                ],
            ),
            f"Order {artist}'s releases dated {release_date}.",
        )
        if choice != "order" or order is None:
            raise slow_listening.SlowListeningError(
                "Slow Listening release order was not submitted."
            )
        return order

    def completion_notifier(source: new_wine.PlaylistTrack) -> None:
        choice, _order = wait_for_submission(
            SlowListeningPendingChoice(
                kind="completion",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
            ),
            (
                f"{source.primary_artist_name} completed Slow Listening. "
                "Add a replacement artist, then continue."
            ),
        )
        if choice != "continue":
            raise slow_listening.SlowListeningError(
                "Slow Listening completion was not acknowledged."
            )

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _SlowListeningJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = slow_listening.flush_slow_listening(
            spotify,
            playlist_id,
            order_reader=order_reader,
            completion_notifier=completion_notifier,
            action_reader=action_reader,
            dry_run=dry_run,
            echo=echo,
            progress_callback=progress_callback,
            retry_call=retry_call,
        )
    except _SlowListeningJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.slow_listening_pending_choice = None
            job.result.detail = (
                "Slow Listening flush stopped. Progress was saved."
                if not dry_run
                else "Slow Listening dry run stopped."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.slow_listening_pending_choice = None
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.slow_listening_pending_choice = None
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + ". "
                "Progress was saved."
            )
            _append_blast_log_locked(job, job.result.detail)
    except (slow_listening.SlowListeningError, SpotifyException) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.slow_listening_pending_choice = None
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Slow Listening flush failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Slow Listening flush error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.slow_listening_pending_choice = None
            job.result.detail = f"Unexpected Slow Listening error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        results = [_slow_listening_track_result(result) for result in summary.results]
        with _blast_jobs_lock:
            job.result.status = "paused" if summary.paused else "completed"
            job.result.processed = summary.processed
            job.result.total = summary.total
            job.result.advanced = summary.advanced
            job.result.completed_artists = summary.completed_artists
            job.result.skipped = summary.skipped
            job.result.slow_listening_results = results
            job.result.slow_listening_pending_choice = None
            if summary.paused:
                job.result.detail = "Slow Listening flush paused. Progress was saved."
            else:
                job.result.detail = (
                    f"{summary.processed}/{summary.total} processed; "
                    f"{summary.advanced} advanced, "
                    f"{summary.completed_artists} artists completed, "
                    f"{summary.skipped} skipped."
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.slow_listening_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _something_old_date(timestamp_ms: int) -> str:
    """Format one scrobble timestamp in the listening timezone."""
    return (
        datetime.fromtimestamp(
            timestamp_ms / 1000,
            blast_from_past.SCROBBLE_TIMEZONE,
        )
        .date()
        .isoformat()
    )


def _something_old_track_result(
    track: something_old.SelectedTrack,
) -> SomethingOldTrackResult:
    """Convert one Something Old selection into its API representation."""
    return SomethingOldTrackResult(
        spotify_id=track.spotify_id,
        track=track.track,
        album=track.album,
        artists=list(track.artists),
        source=track.source,
        lastfm_scrobbles=track.lastfm_scrobbles,
    )


def _run_something_old_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Execute Something Old as a reconnectable interactive web job."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Something Old started"
        _append_blast_log_locked(
            job,
            f"Something Old started{' in dry-run mode' if dry_run else ''}.",
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def wait_for_submission(
        pending: SomethingOldPendingChoice,
        detail: str,
    ) -> str:
        with _blast_jobs_lock:
            if job.cancel_event.is_set():
                raise _SomethingOldJobCancelledError
            job.submitted_choice = None
            job.choice_event.clear()
            job.result.something_old_pending_choice = pending
            job.result.status = "waiting"
            job.result.detail = detail
            _append_blast_log_locked(job, detail)

        while True:
            job.choice_event.wait(0.5)
            with _blast_jobs_lock:
                if job.cancel_event.is_set():
                    raise _SomethingOldJobCancelledError
                choice = job.submitted_choice
                if choice is None:
                    continue
                job.submitted_choice = None
                job.choice_event.clear()
                job.result.something_old_pending_choice = None
                job.result.status = "running"
                job.result.detail = "Applying Something Old choice"
                _append_blast_log_locked(
                    job,
                    f"Something Old choice received: {choice}.",
                )
                return choice

    def artist_choice_reader(
        artist: something_old.GoldenOldieArtist,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        average_date = _something_old_date(artist.average_scrobble_ms)
        with _blast_jobs_lock:
            job.result.something_old_artist = artist.artist
            job.result.something_old_average_scrobble_date = average_date
        return wait_for_submission(
            SomethingOldPendingChoice(
                kind="artist",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=average_date,
                artist_candidates=[
                    SomethingOldArtistOption(
                        spotify_id=candidate.spotify_id,
                        name=candidate.name,
                        popularity=candidate.popularity,
                        followers=candidate.followers,
                    )
                    for candidate in candidates
                ],
            ),
            f"Choose the exact Spotify artist for {artist.artist}.",
        )

    def mode_reader(
        artist: something_old.GoldenOldieArtist,
        spotify_artist: something_old.SpotifyArtistCandidate,
    ) -> str:
        with _blast_jobs_lock:
            job.result.something_old_artist = artist.artist
            job.result.something_old_average_scrobble_date = _something_old_date(
                artist.average_scrobble_ms
            )
            job.result.something_old_spotify_artist = spotify_artist.name
        return wait_for_submission(
            SomethingOldPendingChoice(
                kind="mode",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=_something_old_date(artist.average_scrobble_ms),
                spotify_artist=spotify_artist.name,
            ),
            f"Choose what to add for {artist.artist}.",
        )

    def album_choice_reader(
        artist: something_old.GoldenOldieArtist,
        releases: tuple[slow_listening.DiscographyRelease, ...],
    ) -> str:
        return wait_for_submission(
            SomethingOldPendingChoice(
                kind="album",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=_something_old_date(artist.average_scrobble_ms),
                spotify_artist=job.result.something_old_spotify_artist,
                releases=[
                    SomethingOldReleaseOption(
                        spotify_id=release.spotify_id,
                        name=release.name,
                        release_type=release.release_type,
                        release_date=release.chronology_date,
                        total_tracks=release.total_tracks,
                        saved=release.saved,
                        plain=release.plain,
                    )
                    for release in releases
                ],
            ),
            f"Choose one album or EP by {artist.artist}.",
        )

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _SomethingOldJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    lastfm = LastFmClient(
        api_key,
        username,
        event_callback=echo,
    )
    try:
        summary = something_old.run_something_old(
            spotify,
            lastfm,
            playlist_id,
            expected_username=username,
            mode_reader=mode_reader,
            album_choice_reader=album_choice_reader,
            artist_choice_reader=artist_choice_reader,
            dry_run=dry_run,
            progress_callback=echo,
            retry_call=retry_call,
        )
    except _SomethingOldJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.something_old_pending_choice = None
            job.result.detail = "Something Old stopped. Spotify was unchanged."
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.something_old_pending_choice = None
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.something_old_pending_choice = None
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    datetime.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                job.result.status = "paused"
                job.result.retry_at = retry_at.isoformat() if retry_at else None
                job.result.detail = (
                    "Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}."
                )
            else:
                job.result.status = "failed"
                job.result.detail = str(exc)
            job.result.something_old_pending_choice = None
            _append_blast_log_locked(job, job.result.detail)
    except (
        something_old.SomethingOldError,
        scrobble_history.ScrobbleHistoryError,
        LastFmError,
    ) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.something_old_pending_choice = None
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Something Old failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Something Old error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.something_old_pending_choice = None
            job.result.detail = f"Unexpected Something Old error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        ranking = [
            SomethingOldRankingEntry(
                artist=entry.artist,
                scrobbles=entry.scrobbles,
                average_scrobble_date=_something_old_date(entry.average_scrobble_ms),
            )
            for entry in summary.ranking_preview
        ]
        tracks = [_something_old_track_result(track) for track in summary.tracks]
        with _blast_jobs_lock:
            job.result.status = (
                "cancelled" if summary.action == "cancelled" else "completed"
            )
            job.result.something_old_action = summary.action
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = len(tracks) if summary.action == "added" else 0
            job.result.something_old_ranking = ranking
            job.result.something_old_tracks = tracks
            job.result.something_old_pending_choice = None
            if summary.history_refresh is not None:
                job.result.live_scrobbles_added = (
                    summary.history_refresh.live_scrobbles_added
                )
                job.result.history_scrobbles = summary.history_refresh.total_scrobbles
            if summary.artist is not None:
                job.result.something_old_artist = summary.artist.artist
                job.result.something_old_average_scrobble_date = _something_old_date(
                    summary.artist.average_scrobble_ms
                )
            if summary.spotify_artist is not None:
                job.result.something_old_spotify_artist = summary.spotify_artist.name
            job.result.something_old_mode = summary.mode
            job.result.something_old_release = (
                summary.release.name if summary.release is not None else None
            )
            if summary.action == "playlist not empty":
                job.result.detail = (
                    f"Something Old already contains {summary.playlist_length_before} "
                    "item(s); nothing was changed."
                )
            elif summary.action == "cancelled":
                job.result.detail = "Something Old was cancelled."
            elif summary.action == "would add":
                job.result.detail = (
                    f"Dry run: would add {len(tracks)} track(s) for "
                    f"{job.result.something_old_artist}."
                )
            else:
                job.result.detail = (
                    f"Added {len(tracks)} track(s) for "
                    f"{job.result.something_old_artist}."
                )
            for track in tracks:
                _append_blast_log_locked(
                    job,
                    f"Selected {', '.join(track.artists)} - {track.track} "
                    f"({track.album or 'no album'}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.something_old_pending_choice = None
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_requeue_for_a_dream_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str,
    dry_run: bool,
) -> None:
    """Execute one reconnectable Requeue for a Dream transition."""
    job = get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Requeue for a Dream started"
        _append_blast_log_locked(
            job,
            (
                "Requeue for a Dream started in dry-run mode."
                if dry_run
                else "Requeue for a Dream started."
            ),
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _RequeueForADreamJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        if job.cancel_event.is_set():
            raise _RequeueForADreamJobCancelledError
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        if job.cancel_event.is_set():
            raise _RequeueForADreamJobCancelledError
        return result

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    try:
        summary = requeue_for_a_dream.flush_requeue_for_a_dream(
            spotify,
            playlist_id,
            dry_run=dry_run,
            echo=echo,
            progress_callback=echo,
            retry_call=retry_call,
        )
    except _RequeueForADreamJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = (
                "Requeue for a Dream stopped safely. Rerun it to continue."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    datetime.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                job.result.status = "paused"
                job.result.retry_at = retry_at.isoformat() if retry_at else None
                job.result.detail = (
                    "Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}."
                )
            else:
                job.result.status = "failed"
                job.result.detail = str(exc)
            _append_blast_log_locked(job, job.result.detail)
    except requeue_for_a_dream.RequeueForADreamError as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Requeue for a Dream failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Requeue for a Dream error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Requeue for a Dream error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.requeue_action = summary.action
            job.result.requeue_artist = summary.artist
            job.result.requeue_source_track = summary.source_track
            job.result.requeue_source_release = summary.source_release
            job.result.requeue_target_track = summary.target_track
            job.result.requeue_target_release = summary.target_release
            job.result.requeue_target_release_type = summary.target_release_type
            job.result.requeue_target_release_date = summary.target_release_date
            job.result.requeue_target_already_present = summary.target_already_present
            job.result.playlist_length_before = summary.playlist_length_before
            job.result.playlist_length_after = summary.playlist_length_after
            job.result.added = int(
                summary.action == "advance" and not summary.target_already_present
            )
            if summary.action == "advance":
                verb = "would advance" if dry_run else "advanced"
                job.result.detail = (
                    f"{verb.capitalize()} {summary.artist} from "
                    f"{summary.source_release} to {summary.target_release}."
                )
            elif summary.action == "drop":
                verb = "would drop" if dry_run else "dropped"
                job.result.detail = (
                    f"{verb.capitalize()} {summary.artist} after the final "
                    "eligible release."
                )
            elif summary.action == "empty":
                job.result.detail = "Requeue for a Dream is empty."
            else:
                job.result.detail = (
                    f"Skipped {summary.artist or 'the playlist head'}: "
                    f"{summary.reason or 'no safe transition was found'}."
                )
            if summary.target_track:
                _append_blast_log_locked(
                    job,
                    f"Next track: {summary.target_track} ({summary.target_release}).",
                )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_palace_of_memory_job(
    job_id: str,
    spotify: Spotify,
    playlist_id: str | None,
    dry_run: bool,
    alphabetical_start: str | None,
    cursor_position: int | None,
) -> None:
    """Execute one reconnectable Palace fill or cursor adjustment."""
    job = get_blast_job(job_id, command="fill_palace_of_memory")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = (
            "Setting Palace alphabetical cursor"
            if cursor_position is not None
            else "Palace of Memory started"
        )
        _append_blast_log_locked(job, job.result.detail)

    def echo(message: str) -> None:
        if job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    def interruptible_sleep(seconds: float) -> None:
        if job.cancel_event.wait(seconds):
            raise _PalaceOfMemoryJobCancelledError

    def retry_call(
        operation: Callable[[], object],
        description: str,
    ) -> object:
        if job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=echo,
            sleep=interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        if job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        return result

    spotify_event_setter = getattr(spotify, "set_event_callback", None)
    previous_spotify_event_callback = None
    if callable(spotify_event_setter):
        previous_spotify_event_callback = spotify_event_setter(echo)

    cursor_update: palace_of_memory.AlphabeticalCursorUpdate | None = None
    summary: palace_of_memory.PalaceOfMemorySummary | None = None
    try:
        if cursor_position is not None:
            cursor_update = palace_of_memory.set_alphabetical_cursor(
                spotify,
                cursor_position,
                progress_callback=echo,
                retry_call=retry_call,
            )
        else:
            if playlist_id is None:
                raise palace_of_memory.PalaceOfMemoryConfigError(
                    "Palace of Memory playlist is required."
                )
            summary = palace_of_memory.fill_palace_of_memory(
                spotify,
                playlist_id,
                dry_run=dry_run,
                alphabetical_start=alphabetical_start,
                echo=echo,
                progress_callback=echo,
                retry_call=retry_call,
            )
    except _PalaceOfMemoryJobCancelledError:
        with _blast_jobs_lock:
            job.result.status = "cancelled"
            job.result.detail = "Palace of Memory stopped safely. Rerun it to continue."
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyRateLimitError as exc:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = datetime.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.retry_at = retry_at.isoformat() if retry_at else None
            job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}."
            )
            _append_blast_log_locked(job, job.result.detail)
    except review_album_limits.SpotifyTransientServerError as exc:
        with _blast_jobs_lock:
            job.result.status = "paused"
            job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            _append_blast_log_locked(job, job.result.detail)
    except SpotifyException as exc:
        with _blast_jobs_lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    datetime.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                job.result.status = "paused"
                job.result.retry_at = retry_at.isoformat() if retry_at else None
                job.result.detail = (
                    "Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}."
                )
            else:
                job.result.status = "failed"
                job.result.detail = str(exc)
            _append_blast_log_locked(job, job.result.detail)
    except palace_of_memory.PalaceOfMemoryError as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Palace of Memory failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected Palace of Memory error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected Palace of Memory error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        with _blast_jobs_lock:
            job.result.status = "completed"
            if cursor_update is not None:
                refresh = cursor_update.album_refresh
                job.result.palace_alphabetical_start_index = cursor_update.next_index
                job.result.palace_alphabetical_next_index = cursor_update.next_index
                job.result.palace_next_album_artist = cursor_update.next_album.artist
                job.result.palace_next_album = cursor_update.next_album.album
                job.result.detail = (
                    f"Alphabetical cursor set to {cursor_update.next_index + 1}: "
                    f"{cursor_update.next_album.artist} - "
                    f"{cursor_update.next_album.album}."
                )
            elif summary is not None:
                refresh = summary.album_refresh
                job.result.random_org_timestamp = summary.generated_at.isoformat()
                job.result.palace_cutoff_date = summary.cutoff_date.isoformat()
                job.result.palace_available_dates = summary.available_dates
                job.result.palace_alphabetical_start_index = (
                    summary.alphabetical_start_index
                )
                job.result.palace_alphabetical_next_index = (
                    summary.alphabetical_next_index
                )
                job.result.palace_alphabetical_cursor_overridden = (
                    summary.alphabetical_cursor_overridden
                )
                job.result.playlist_length_before = summary.playlist_length_before
                job.result.playlist_length_after = summary.playlist_length_after
                job.result.added = summary.added
                job.result.palace_results = [
                    PalaceAlbumSelectionResult(
                        source=result.source,
                        selected_date=(
                            result.selected_date.isoformat()
                            if result.selected_date is not None
                            else None
                        ),
                        history_position=result.history_position,
                        albums_on_date=result.albums_on_date,
                        artist=result.artist,
                        album=result.album,
                        spotify_album=(
                            result.spotify_album.album
                            if result.spotify_album is not None
                            else None
                        ),
                        first_track=(
                            result.first_track.name
                            if result.first_track is not None
                            else None
                        ),
                        action=result.action,
                    )
                    for result in summary.results
                ]
                verb = "Would add" if dry_run else "Added"
                job.result.detail = (
                    f"{verb} {summary.added} first track(s) to Palace of Memory."
                )
                for result in job.result.palace_results:
                    _append_blast_log_locked(
                        job,
                        f"{result.source.title()}: {result.artist} - "
                        f"{result.album} -> {result.first_track or 'no match'} "
                        f"({result.action}).",
                    )
            else:  # pragma: no cover - defensive worker invariant
                raise AssertionError("Palace worker completed without a result")

            job.result.palace_album_refresh = PalaceAlbumRefreshResult(
                previous=refresh.previous,
                current=refresh.current,
                added=refresh.added,
                removed=refresh.removed,
                skipped=refresh.skipped,
                persisted=refresh.persisted,
                backup_path=refresh.backup_path,
            )
            _append_blast_log_locked(job, job.result.detail)
    finally:
        if callable(spotify_event_setter):
            spotify_event_setter(previous_spotify_event_callback)
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def _run_scrobble_history_job(
    job_id: str,
    api_key: str,
    username: str,
    dry_run: bool,
) -> None:
    """Refresh the shared Last.fm record as a reconnectable web job."""
    job = get_blast_job(job_id, command="update_scrobble_history")
    with _blast_jobs_lock:
        job.result.status = "running"
        job.result.started_at = datetime.now(UTC).isoformat()
        job.result.detail = "Last.fm scrobble history update started"
        _append_blast_log_locked(
            job,
            (
                "Last.fm scrobble history update started in dry-run mode."
                if dry_run
                else "Last.fm scrobble history update started."
            ),
        )

    def echo(message: str) -> None:
        with _blast_jobs_lock:
            job.result.detail = message
            _append_blast_log_locked(job, message)

    lastfm = LastFmClient(
        api_key,
        username,
        event_callback=echo,
    )
    try:
        summary = scrobble_history.refresh_scrobble_history(
            lastfm,
            expected_username=username,
            dry_run=dry_run,
            progress_callback=echo,
        )
    except (scrobble_history.ScrobbleHistoryError, LastFmError) as exc:
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = str(exc)
            _append_blast_log_locked(job, f"Scrobble history update failed: {exc}")
    except Exception as exc:  # pragma: no cover - last-resort worker boundary
        _analysis_logger.exception("Unexpected scrobble history update error")
        with _blast_jobs_lock:
            job.result.status = "failed"
            job.result.detail = f"Unexpected scrobble history update error: {exc}"
            _append_blast_log_locked(job, job.result.detail)
    else:
        with _blast_jobs_lock:
            job.result.status = "completed"
            job.result.history_export_scrobbles = summary.export_scrobbles
            job.result.history_legacy_scrobbles_added = summary.legacy_scrobbles_added
            job.result.live_scrobbles_added = summary.live_scrobbles_added
            job.result.history_scrobbles = summary.total_scrobbles
            job.result.history_persisted = summary.persisted
            job.result.history_backup_path = (
                str(summary.backup_path) if summary.backup_path else None
            )
            if summary.dry_run:
                job.result.detail = (
                    "Dry run complete; the canonical Last.fm history was unchanged."
                )
            elif summary.persisted:
                job.result.detail = "Last.fm scrobble history updated safely."
            else:
                job.result.detail = "Last.fm scrobble history was already current."
            _append_blast_log_locked(job, job.result.detail)
    finally:
        with _blast_jobs_lock:
            job.result.completed_at = datetime.now(UTC).isoformat()


def start_blast_job(
    spotify: Spotify,
    playlist_id: str,
    count: int | None,
    max_playlist_length: int | None,
) -> BlastJobResult:
    """Start one playlist job, rejecting another active invocation."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(result=BlastJobResult(job_id=job_id))
        _append_blast_log_locked(job, "A blast from the past queued.")
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_blast_job,
        args=(job_id, spotify, playlist_id, count, max_playlist_length),
        name=f"blast-from-the-past-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_daily_mind_radio_job(
    spotify: Spotify,
    playlist_id: str,
) -> BlastJobResult:
    """Start one Daily Mind Radio job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="daily_mind_radio",
            )
        )
        _append_blast_log_locked(job, "Daily Mind Radio queued.")
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_daily_mind_radio_job,
        args=(job_id, spotify, playlist_id),
        name=f"daily-mind-radio-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_found_art_job(
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    count: int,
) -> BlastJobResult:
    """Start one Found Art job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="found_art",
                requested_count=count,
            )
        )
        _append_blast_log_locked(job, "Found Art queued.")
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_found_art_job,
        args=(job_id, spotify, playlist_id, api_key, username, count),
        name=f"found-art-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_new_wine_job(
    spotify: Spotify,
    new_wine_playlist_id: str,
    sauvignon_playlist_id: str,
    wine_cellar_playlist_id: str,
    *,
    dry_run: bool,
    no_discovery: bool,
) -> BlastJobResult:
    """Start one New Wine web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_new_wine",
                dry_run=dry_run,
                no_discovery=no_discovery,
            )
        )
        _append_blast_log_locked(
            job,
            f"New Wine flush queued{' in dry-run mode' if dry_run else ''}.",
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_new_wine_job,
        args=(
            job_id,
            spotify,
            new_wine_playlist_id,
            sauvignon_playlist_id,
            wine_cellar_playlist_id,
            dry_run,
            no_discovery,
        ),
        name=f"new-wine-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_slow_listening_job(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one Slow Listening web job, rejecting another playlist routine."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_slow_listening",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Slow Listening flush queued in dry-run mode."
                if dry_run
                else "Slow Listening flush queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_slow_listening_job,
        args=(job_id, spotify, playlist_id, dry_run),
        name=f"slow-listening-flush-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_something_old_job(
    spotify: Spotify,
    playlist_id: str,
    api_key: str,
    username: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one interactive Something Old job with reload-safe state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="something_old",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Something Old queued in dry-run mode."
                if dry_run
                else "Something Old queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_something_old_job,
        args=(job_id, spotify, playlist_id, api_key, username, dry_run),
        name=f"something-old-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_requeue_for_a_dream_job(
    spotify: Spotify,
    playlist_id: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one Requeue for a Dream job with reload-safe state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="flush_requeue_for_a_dream",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Requeue for a Dream queued in dry-run mode."
                if dry_run
                else "Requeue for a Dream queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_requeue_for_a_dream_job,
        args=(job_id, spotify, playlist_id, dry_run),
        name=f"requeue-for-a-dream-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_palace_of_memory_job(
    spotify: Spotify,
    playlist_id: str | None,
    *,
    dry_run: bool,
    alphabetical_start: str | None,
    cursor_position: int | None,
) -> BlastJobResult:
    """Start one reload-safe Palace fill or cursor adjustment."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist routine is already running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        cursor_only = cursor_position is not None
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="fill_palace_of_memory",
                dry_run=dry_run,
                palace_cursor_only=cursor_only,
                palace_alphabetical_reference=(
                    str(cursor_position) if cursor_only else alphabetical_start
                ),
            )
        )
        queued_message = (
            f"Palace alphabetical cursor adjustment to {cursor_position} queued."
            if cursor_only
            else (
                "Palace of Memory queued in dry-run mode."
                if dry_run
                else "Palace of Memory queued."
            )
        )
        _append_blast_log_locked(job, queued_message)
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_palace_of_memory_job,
        args=(
            job_id,
            spotify,
            playlist_id,
            dry_run,
            alphabetical_start,
            cursor_position,
        ),
        name=f"palace-of-memory-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


def start_scrobble_history_job(
    api_key: str,
    username: str,
    *,
    dry_run: bool,
) -> BlastJobResult:
    """Start one shared Last.fm history refresh with reload-safe state."""
    with _blast_jobs_lock:
        for existing in _blast_jobs.values():
            if existing.result.status in _ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "another playlist or history routine is running",
                        "job_id": existing.result.job_id,
                        "command": existing.result.command,
                    },
                )
        job_id = uuid4().hex
        job = _BlastJob(
            result=BlastJobResult(
                job_id=job_id,
                command="update_scrobble_history",
                dry_run=dry_run,
            )
        )
        _append_blast_log_locked(
            job,
            (
                "Last.fm scrobble history update queued in dry-run mode."
                if dry_run
                else "Last.fm scrobble history update queued."
            ),
        )
        _blast_jobs[job_id] = job
        snapshot = _blast_job_snapshot(job)

    Thread(
        target=_run_scrobble_history_job,
        args=(job_id, api_key, username, dry_run),
        name=f"scrobble-history-{job_id[:8]}",
        daemon=True,
    ).start()
    return snapshot


app = FastAPI(title="Spotify Manager", version="0.1.0")


@app.exception_handler(ArtistNotFoundError)
def _artist_not_found(request: Request, exc: ArtistNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousArtistError)
def _ambiguous_artist(request: Request, exc: AmbiguousArtistError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": str(exc), "candidates": exc.candidates},
    )


@app.exception_handler(AlbumNotFoundError)
def _album_not_found(request: Request, exc: AlbumNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousAlbumError)
def _ambiguous_album(request: Request, exc: AmbiguousAlbumError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
    )


@app.exception_handler(SpotifyLookupResponseError)
def _invalid_spotify_lookup(
    request: Request,
    exc: SpotifyLookupResponseError,
) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(SpotifyException)
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
            status_code=429,
            content={"detail": detail},
            headers=headers,
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


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/auth/check")
def auth_check() -> dict[str, str]:
    """Side-effect-free password check protected by the deployment middleware."""
    return {"status": "ok"}


@app.post("/library/refresh", response_model=CommandResult)
def refresh_library() -> CommandResult:
    """Drop the cached library so the next request re-reads YourLibrary.json."""
    get_library.cache_clear()
    return CommandResult(command="library_refresh")


# --------------------------------------------------------------------------- #
# Live Spotify lookups
# --------------------------------------------------------------------------- #
@app.get("/artists/stats", response_model=ArtistLibraryStats)
def artist_stats(
    client: ClientDep,
    name: Annotated[str | None, Query()] = None,
    artist_id: Annotated[str | None, Query()] = None,
) -> ArtistLibraryStats:
    """Return live Liked Songs and Saved Albums counts for one artist."""
    if not name and not artist_id:
        raise HTTPException(status_code=400, detail="provide name or artist_id")
    try:
        return get_live_artist_library_stats(
            client,
            name=name,
            artist_id=artist_id,
        )
    except RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Spotify could not be reached after several attempts. "
                "Please try again shortly."
            ),
        ) from exc


@app.get("/albums/evaluation", response_model=AlbumEvaluation)
def album_evaluation(
    client: ClientDep,
    name: Annotated[str | None, Query()] = None,
    album_id: Annotated[str | None, Query()] = None,
    artist: Annotated[str | None, Query()] = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Return a keep/remove decision from live Spotify album and liked state."""
    if not name and not album_id:
        raise HTTPException(status_code=400, detail="provide name or album_id")
    try:
        return evaluate_album_live(
            client,
            name=name,
            album_id=album_id,
            artist=artist,
            threshold=threshold,
        )
    except RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Spotify could not be reached after several attempts. "
                "Please try again shortly."
            ),
        ) from exc


# --------------------------------------------------------------------------- #
# Mirrored CLI commands
# --------------------------------------------------------------------------- #
@app.post("/commands/monthly-routines", response_model=CommandResult)
def cmd_monthly_routines(client: ClientDep) -> CommandResult:
    """Run the full monthly routine (compare, convert, monthly)."""
    compare_your_library_and_all_albums()
    convert_your_library_file(client)
    run_monthly_routines(client)
    return CommandResult(command="monthly_routines")


@app.post("/commands/update-total-albums", response_model=CommandResult)
def cmd_update_total_albums(
    client: ClientDep, just_update: bool = False
) -> CommandResult:
    """Update the total album list."""
    albums = update_total_album_list(client, just_update)
    return CommandResult(
        command="update_total_albums", detail=f"{len(albums)} albums in list"
    )


@app.post("/commands/restore-your-library", response_model=CommandResult)
def cmd_restore_your_library(client: ClientDep) -> CommandResult:
    """Restore artists and tracks from the YourLibrary file."""
    restore_your_library_from_file(client)
    return CommandResult(command="restore_your_library")


@app.post("/commands/compare-lib-files", response_model=CommandResult)
def cmd_compare_lib_files() -> CommandResult:
    """Create the comparison between YourLibrary and the total-albums file."""
    compare_your_library_and_all_albums()
    return CommandResult(command="compare_lib_files")


@app.post("/commands/analyse-comp", response_model=CommandResult)
def cmd_analyse_comp(client: ClientDep) -> CommandResult:
    """Analyse the saved comparison file against the live library."""
    analyse_comparison(client)
    return CommandResult(command="analyse_comp")


@app.post("/commands/convert-lib", response_model=CommandResult)
def cmd_convert_lib(client: ClientDep) -> CommandResult:
    """Convert the YourLibrary file into the total-albums file."""
    convert_your_library_file(client)
    return CommandResult(command="convert_lib")


@app.get("/commands/count-artists", response_model=CountResult)
def cmd_count_artists() -> CountResult:
    """Count the artists in the YourLibrary file."""
    return CountResult(count=count_artists_in_library())


@app.post(
    "/commands/blast-from-the-past",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_blast_from_the_past(
    client: ClientDep,
    count: Annotated[int | None, Query(ge=1)] = None,
    max_playlist_length: Annotated[int | None, Query(ge=1)] = None,
) -> BlastJobResult:
    """Start a background Friday-routine playlist update."""
    if count is not None and max_playlist_length is not None:
        raise HTTPException(
            status_code=400,
            detail="use either count or max_playlist_length, not both",
        )
    effective_count = 10 if count is None and max_playlist_length is None else count
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            Settings().blast_from_the_past_playlist
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_blast_job(
        client,
        playlist_id,
        effective_count,
        max_playlist_length,
    )


@app.get(
    "/commands/blast-from-the-past-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_blast_jobs() -> list[BlastJobResult]:
    """Return active playlist jobs so the web UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "blast_from_the_past"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/blast-from-the-past-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_blast_job(job_id: str) -> BlastJobResult:
    """Return current progress for one playlist job."""
    job = get_blast_job(job_id, command="blast_from_the_past")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/daily-mind-radio",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_daily_mind_radio(client: ClientDep) -> BlastJobResult:
    """Start a background Daily Mind Radio anniversary update."""
    try:
        playlist_id = blast_from_past.parse_playlist_id(
            Settings().daily_mind_radio_playlist,
            setting_name="DAILY_MIND_RADIO_PLAYLIST",
        )
    except blast_from_past.BlastFromPastConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_daily_mind_radio_job(client, playlist_id)


@app.get(
    "/commands/daily-mind-radio-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_daily_mind_radio_jobs() -> list[BlastJobResult]:
    """Return active Daily Mind Radio jobs for web reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "daily_mind_radio"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/daily-mind-radio-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_daily_mind_radio_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Daily Mind Radio job."""
    job = get_blast_job(job_id, command="daily_mind_radio")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/found-art",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_found_art(
    client: ClientDep,
    count: Annotated[int, Query(ge=1)] = found_art.DEFAULT_COUNT,
) -> BlastJobResult:
    """Start a background Found Art recommendation update."""
    configuration = Settings()
    try:
        playlist_id = found_art.parse_found_art_playlist_id(
            configuration.found_art_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_found_art_job(
        client,
        playlist_id,
        api_key,
        username,
        count,
    )


@app.get(
    "/commands/found-art-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_found_art_jobs() -> list[BlastJobResult]:
    """Return active Found Art jobs for web reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "found_art"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/found-art-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_found_art_job(job_id: str) -> BlastJobResult:
    """Return current progress for one Found Art job."""
    job = get_blast_job(job_id, command="found_art")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-wine",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_new_wine(
    client: InteractiveClientDep,
    dry_run: bool = True,
    no_discovery: bool = False,
) -> BlastJobResult:
    """Start an interactive New Wine flush with reconnectable web state."""
    configuration = Settings()
    try:
        new_wine_playlist_id = new_wine.parse_playlist_id(
            configuration.new_wine_from_old_bottles_playlist,
            "NEW_WINE_FROM_OLD_BOTTLES_PLAYLIST",
        )
        sauvignon_playlist_id = new_wine.parse_playlist_id(
            configuration.sauvignon_terre_neuve_playlist,
            "SAUVIGNON_TERRE_NEUVE_PLAYLIST",
        )
        wine_cellar_playlist_id = new_wine.parse_playlist_id(
            configuration.wine_cellar_playlist,
            "WINE_CELLAR_PLAYLIST",
        )
    except new_wine.NewWineConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_new_wine_job(
        client,
        new_wine_playlist_id,
        sauvignon_playlist_id,
        wine_cellar_playlist_id,
        dry_run=dry_run,
        no_discovery=no_discovery,
    )


@app.get(
    "/commands/flush-new-wine-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_new_wine_jobs() -> list[BlastJobResult]:
    """Return active New Wine jobs so the web UI can reconnect after reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_new_wine"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-new-wine-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_new_wine_job(job_id: str) -> BlastJobResult:
    """Return current progress and any pending choice for one New Wine job."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-wine-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_new_wine_release(
    job_id: str,
    request: NewWineChoiceRequest,
) -> BlastJobResult:
    """Submit one release or control choice to a waiting New Wine job."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        pending = job.result.pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="New Wine job is not waiting for a release choice",
            )
        allowed = {
            new_wine.CHOICE_DROP,
            new_wine.CHOICE_SKIP,
            new_wine.CHOICE_QUIT,
            *(release.spotify_id for release in pending.releases),
        }
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400,
                detail="release choice is not available",
            )
        job.submitted_choice = request.choice
        job.result.pending_choice = None
        job.result.status = "running"
        job.result.detail = "Release choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-new-wine-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_new_wine_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next New Wine processing boundary."""
    job = get_blast_job(job_id, command="flush_new_wine")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="New Wine job is not active")
        job.result.status = "cancelling"
        job.result.pending_choice = None
        job.result.detail = "Stopping New Wine flush"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-slow-listening",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_slow_listening(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an interactive Slow Listening flush with reconnectable state."""
    configuration = Settings()
    try:
        playlist_id = slow_listening.parse_playlist_id(
            configuration.slow_listening_playlist
        )
    except slow_listening.SlowListeningConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_slow_listening_job(
        client,
        playlist_id,
        dry_run=dry_run,
    )


@app.get(
    "/commands/flush-slow-listening-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_slow_listening_jobs() -> list[BlastJobResult]:
    """Return active Slow Listening jobs for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_slow_listening"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-slow-listening-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_slow_listening_job(job_id: str) -> BlastJobResult:
    """Return current progress and the pending Slow Listening choice."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-slow-listening-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_slow_listening_track(
    job_id: str,
    request: SlowListeningChoiceRequest,
) -> BlastJobResult:
    """Submit a candidate, release order, or completion acknowledgement."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        pending = job.result.slow_listening_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Slow Listening job is not waiting for a choice",
            )

        submitted_order: tuple[str, ...] | None = None
        if pending.kind == "track":
            allowed = {
                slow_listening.CHOICE_ADVANCE,
                slow_listening.CHOICE_SKIP,
                slow_listening.CHOICE_QUIT,
            }
            if request.choice not in allowed or request.order:
                raise HTTPException(
                    status_code=400,
                    detail="track choice is not available",
                )
        elif pending.kind == "release_order":
            expected_ids = {release.spotify_id for release in pending.releases}
            submitted_order = tuple(request.order)
            if (
                request.choice != "order"
                or len(submitted_order) != len(expected_ids)
                or set(submitted_order) != expected_ids
            ):
                raise HTTPException(
                    status_code=400,
                    detail="release order must include every option exactly once",
                )
        elif request.choice != "continue" or request.order:
            raise HTTPException(
                status_code=400,
                detail="completion choice is not available",
            )

        job.submitted_choice = request.choice
        job.submitted_order = submitted_order
        job.result.slow_listening_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Slow Listening choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-slow-listening-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_slow_listening_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Slow Listening boundary."""
    job = get_blast_job(job_id, command="flush_slow_listening")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Slow Listening job is not active",
            )
        job.result.status = "cancelling"
        job.result.slow_listening_pending_choice = None
        job.result.detail = "Stopping Slow Listening flush"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/something-old",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_something_old(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start an interactive Something Old selection with reconnectable state."""
    configuration = Settings()
    try:
        playlist_id = something_old.parse_playlist_id(
            configuration.something_old_new_playlist
        )
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except (
        something_old.SomethingOldConfigError,
        found_art.FoundArtConfigError,
    ) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_something_old_job(
        client,
        playlist_id,
        api_key,
        username,
        dry_run=dry_run,
    )


@app.get(
    "/commands/something-old-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_something_old_jobs() -> list[BlastJobResult]:
    """Return active Something Old jobs for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "something_old"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/something-old-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_something_old_job(job_id: str) -> BlastJobResult:
    """Return current Something Old progress and any pending choice."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/something-old-jobs/{job_id}/choice",
    response_model=BlastJobResult,
)
def cmd_choose_something_old(
    job_id: str,
    request: SomethingOldChoiceRequest,
) -> BlastJobResult:
    """Submit an exact artist, source mode, album/EP, or quit choice."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        pending = job.result.something_old_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(
                status_code=409,
                detail="Something Old job is not waiting for a choice",
            )

        if pending.kind == "artist":
            allowed = {
                "quit",
                *(candidate.spotify_id for candidate in pending.artist_candidates),
            }
        elif pending.kind == "mode":
            allowed = {
                "lastfm_top_tracks",
                "spotify_top_tracks",
                "album",
                "quit",
            }
        else:
            allowed = {
                "quit",
                *(release.spotify_id for release in pending.releases),
            }
        if request.choice not in allowed:
            raise HTTPException(
                status_code=400,
                detail="Something Old choice is not available",
            )

        job.submitted_choice = request.choice
        job.result.something_old_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Something Old choice submitted"
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/something-old-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_something_old_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next Something Old boundary."""
    job = get_blast_job(job_id, command="something_old")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Something Old job is not active",
            )
        job.result.status = "cancelling"
        job.result.something_old_pending_choice = None
        job.result.detail = "Stopping Something Old"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        job.choice_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-requeue-for-a-dream",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_flush_requeue_for_a_dream(
    client: InteractiveClientDep,
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a reconnectable Requeue for a Dream transition."""
    configuration = Settings()
    try:
        playlist_id = requeue_for_a_dream.parse_playlist_id(
            configuration.reqeueue_for_a_dream_playlist
        )
    except requeue_for_a_dream.RequeueForADreamConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_requeue_for_a_dream_job(
        client,
        playlist_id,
        dry_run=dry_run,
    )


@app.get(
    "/commands/flush-requeue-for-a-dream-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_requeue_for_a_dream_jobs() -> list[BlastJobResult]:
    """Return active Requeue for a Dream jobs after a page reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "flush_requeue_for_a_dream"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/flush-requeue-for-a-dream-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one Requeue transition."""
    job = get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/flush-requeue-for-a-dream-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_requeue_for_a_dream_job(job_id: str) -> BlastJobResult:
    """Request a clean stop at the next API or retry boundary."""
    job = get_blast_job(job_id, command="flush_requeue_for_a_dream")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Requeue for a Dream job is not active",
            )
        job.result.status = "cancelling"
        job.result.detail = "Stopping Requeue for a Dream"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-palace-of-memory",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_fill_palace_of_memory(
    client: InteractiveClientDep,
    dry_run: bool = True,
    alphabetical_start: str | None = None,
    set_alphabetical_cursor: int | None = Query(default=None, ge=1),
) -> BlastJobResult:
    """Start a reconnectable Palace fill or cursor-only adjustment."""
    cleaned_start = alphabetical_start.strip() if alphabetical_start else None
    if set_alphabetical_cursor is not None and dry_run:
        raise HTTPException(
            status_code=400,
            detail=(
                "set_alphabetical_cursor persists immediately and cannot use dry_run"
            ),
        )
    if set_alphabetical_cursor is not None and cleaned_start is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "use either set_alphabetical_cursor or alphabetical_start, not both"
            ),
        )

    playlist_id = None
    if set_alphabetical_cursor is None:
        configuration = Settings()
        try:
            playlist_id = palace_of_memory.parse_playlist_id(
                configuration.palace_of_memory_playlist
            )
        except palace_of_memory.PalaceOfMemoryConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return start_palace_of_memory_job(
        client,
        playlist_id,
        dry_run=dry_run,
        alphabetical_start=cleaned_start,
        cursor_position=set_alphabetical_cursor,
    )


@app.get(
    "/commands/fill-palace-of-memory-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_palace_of_memory_jobs() -> list[BlastJobResult]:
    """Return active Palace jobs after a page reload."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "fill_palace_of_memory"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/fill-palace-of-memory-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Return current Palace progress, results, and logs."""
    job = get_blast_job(job_id, command="fill_palace_of_memory")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/fill-palace-of-memory-jobs/{job_id}/cancel",
    response_model=BlastJobResult,
)
def cmd_cancel_palace_of_memory_job(job_id: str) -> BlastJobResult:
    """Request a clean Palace stop at the next API or retry boundary."""
    job = get_blast_job(job_id, command="fill_palace_of_memory")
    with _blast_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Palace of Memory job is not active",
            )
        job.result.status = "cancelling"
        job.result.detail = "Stopping Palace of Memory"
        _append_blast_log_locked(job, job.result.detail)
        job.cancel_event.set()
        return _blast_job_snapshot(job)


@app.post(
    "/commands/update-scrobble-history",
    response_model=BlastJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_update_scrobble_history(
    dry_run: bool = True,
) -> BlastJobResult:
    """Start a background refresh of the shared Last.fm scrobble record."""
    configuration = Settings()
    try:
        api_key, username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key,
            configuration.lastfm_username,
        )
    except found_art.FoundArtConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return start_scrobble_history_job(
        api_key,
        username,
        dry_run=dry_run,
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
    return ServerFileStatus(
        filename=path.name,
        exists=True,
        updated_at=modified_at,
    )


@app.get(
    "/library-mirrors/status",
    response_model=LibraryMirrorFilesStatus,
)
def library_mirror_files_status() -> LibraryMirrorFilesStatus:
    """Return update timestamps for New Wine's canonical mirror files."""
    return LibraryMirrorFilesStatus(
        files=[_server_file_status(path) for path in LIBRARY_MIRROR_FILE_PATHS]
    )


@app.get(
    "/commands/update-scrobble-history-jobs",
    response_model=list[BlastJobResult],
)
def cmd_active_scrobble_history_jobs() -> list[BlastJobResult]:
    """Return active history refreshes for page-reload reconnection."""
    with _blast_jobs_lock:
        return [
            _blast_job_snapshot(job)
            for job in _blast_jobs.values()
            if job.result.command == "update_scrobble_history"
            and job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/update-scrobble-history-jobs/{job_id}",
    response_model=BlastJobResult,
)
def cmd_scrobble_history_job(job_id: str) -> BlastJobResult:
    """Return the current state and logs for one history refresh."""
    job = get_blast_job(job_id, command="update_scrobble_history")
    with _blast_jobs_lock:
        return _blast_job_snapshot(job)


@app.post(
    "/commands/analyse-library-async",
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_analyse_library_async() -> AnalysisJobResult:
    """Start an export-only ``*_async`` library analysis."""
    return start_analysis_job("async")


@app.post(
    "/commands/analyse-library-sync",
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_analyse_library_sync(client: AnalysisClientDep) -> AnalysisJobResult:
    """Start a live-only ``*_sync`` library analysis."""
    return start_analysis_job("sync", client)


@app.post(
    "/commands/refresh-library-mirrors",
    response_model=AnalysisJobResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def cmd_refresh_library_mirrors(
    client: AnalysisClientDep,
    full_rebuild: bool = False,
) -> AnalysisJobResult:
    """Refresh canonical saved-album and liked-track mirrors from Spotify."""
    return start_analysis_job("mirrors", client, full_rebuild=full_rebuild)


@app.get(
    "/commands/library-analysis-jobs",
    response_model=list[AnalysisJobResult],
)
def cmd_active_library_analysis_jobs() -> list[AnalysisJobResult]:
    """Return active analyses so the web UI can reconnect after a reload."""
    with _analysis_jobs_lock:
        return [
            _job_snapshot(job)
            for job in _analysis_jobs.values()
            if job.result.status in _ACTIVE_JOB_STATUSES
        ]


@app.get(
    "/commands/library-analysis-jobs/{job_id}",
    response_model=AnalysisJobResult,
)
def cmd_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Return current progress for one library analysis job."""
    job = get_analysis_job(job_id)
    with _analysis_jobs_lock:
        return _job_snapshot(job)


@app.post(
    "/commands/library-analysis-jobs/{job_id}/cancel",
    response_model=AnalysisJobResult,
)
def cmd_cancel_library_analysis_job(job_id: str) -> AnalysisJobResult:
    """Request a clean stop at the next durable analysis boundary."""
    job = get_analysis_job(job_id)
    with _analysis_jobs_lock:
        if job.result.status not in _ACTIVE_JOB_STATUSES:
            raise HTTPException(status_code=409, detail="analysis job is not active")
        job.cancel_event.set()
        job.result.status = "cancelling"
        job.result.detail = "Saving progress and stopping"
        _append_job_log_locked(job, "Cancellation requested; saving progress.")
        return _job_snapshot(job)


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Run the API with uvicorn (entry point for the ``spotify-api`` script)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)
