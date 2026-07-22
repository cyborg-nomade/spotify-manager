"""FastAPI interface exposing the same logic as the Typer CLI.

Run with::

    uvicorn spotify_manager.api:app --reload

or via the installed script ``spotify-api``.

The two lookups are files-first (source of truth: ``YourLibrary.json``).
``artist-stats`` is fully local; ``album-evaluation`` makes a single live call
to fetch the album's track list. Library analyses run as cancellable background
jobs with pollable progress. The parsed library is cached; call
``POST /library/refresh`` after re-exporting YourLibrary.json.
"""

import logging
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
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
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import evaluate_album
from spotify_manager.processors.library_lookups import get_artist_library_stats
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.routines import analyse_library as library_analysis
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import daily_mind_radio
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
    resources: dict[str, AnalysisResourceProgress]
    logs: list[AnalysisJobLog] = Field(default_factory=list)


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


_analysis_jobs: dict[str, _AnalysisJob] = {}
_analysis_jobs_lock = Lock()
_ACTIVE_JOB_STATUSES = {"queued", "running", "waiting", "cancelling"}
_MAX_ANALYSIS_LOGS = 250
_analysis_logger = logging.getLogger(__name__)
_blast_jobs: dict[str, _BlastJob] = {}
_blast_jobs_lock = Lock()
_MAX_BLAST_LOGS = 250


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
def get_library() -> YourLibraryFile:
    """Provide the parsed YourLibrary.json, cached for the process."""
    return load_your_library_file()


ClientDep = Annotated[Spotify, Depends(get_client)]
AnalysisClientDep = Annotated[Spotify, Depends(get_analysis_client)]
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
        with _analysis_jobs_lock:
            job.result.status = "waiting"
            job.result.retry_at = retry_at.isoformat()
            job.result.detail = (
                f"Spotify HTTP {notice.http_status}; retry {notice.attempt} "
                f"while {notice.operation}"
            )
            _append_job_log_locked(
                job,
                f"Waiting until {retry_at.isoformat()} before retry "
                f"{notice.attempt} after Spotify HTTP {notice.http_status} "
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
        else:
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
) -> AnalysisJobResult:
    """Start one background analysis, rejecting duplicate active modes."""
    command = f"analyse_library_{mode}"
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
                resources={
                    resource: AnalysisResourceProgress()
                    for resource in ("albums", "tracks", "artists")
                },
            ),
            cancel_event=Event(),
        )
        _append_job_log_locked(job, f"{mode.title()} analysis queued.")
        _analysis_jobs[job_id] = job
        snapshot = _job_snapshot(job)

    Thread(
        target=_run_analysis_job,
        args=(job_id, mode, spotify),
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


app = FastAPI(title="Spotify Manager", version="0.1.0")


@app.exception_handler(ArtistNotFoundError)
def _artist_not_found(request: Request, exc: ArtistNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AlbumNotFoundError)
def _album_not_found(request: Request, exc: AlbumNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(AmbiguousAlbumError)
def _ambiguous_album(request: Request, exc: AmbiguousAlbumError) -> JSONResponse:
    return JSONResponse(
        status_code=409, content={"detail": str(exc), "candidates": exc.candidates}
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
# Lookups (files-first)
# --------------------------------------------------------------------------- #
@app.get("/artists/stats", response_model=ArtistLibraryStats)
def artist_stats(
    library: LibraryDep,
    name: Annotated[str | None, Query()] = None,
    artist_id: Annotated[str | None, Query()] = None,
) -> ArtistLibraryStats:
    """Liked-track and saved-release counts for an artist (local files only)."""
    if not name and not artist_id:
        raise HTTPException(status_code=400, detail="provide name or artist_id")
    return get_artist_library_stats(name=name, artist_id=artist_id, library=library)


@app.get("/albums/evaluation", response_model=AlbumEvaluation)
def album_evaluation(
    client: ClientDep,
    library: LibraryDep,
    name: Annotated[str | None, Query()] = None,
    album_id: Annotated[str | None, Query()] = None,
    artist: Annotated[str | None, Query()] = None,
    threshold: float = 0.5,
    use_cache: bool = True,
    refresh_cache: bool = False,
) -> AlbumEvaluation:
    """Keep/remove decision for an album (album id resolved locally)."""
    if not name and not album_id:
        raise HTTPException(status_code=400, detail="provide name or album_id")
    return evaluate_album(
        client,
        name=name,
        album_id=album_id,
        artist=artist,
        library=library,
        threshold=threshold,
        use_cache=use_cache,
        refresh_cache=refresh_cache,
    )


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
