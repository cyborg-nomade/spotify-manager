"""Own export review tokens and schedule confirmed work on the web job runtime."""

from dataclasses import dataclass
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException

from spotify_manager.application.listening_export import PlaylistExportJob
from spotify_manager.application.listening_export import PlaylistGateway
from spotify_manager.application.listening_export import run_playlist_export
from spotify_manager.domain.listening_export import ExportPlan
from spotify_manager.infrastructure.async_jobs import JobTasks
from spotify_manager.infrastructure.async_signal import AsyncSignal
from spotify_manager.interfaces.http.job_registry import register_job
from spotify_manager.interfaces.http.job_registry import require_slot


_REVIEW_SECONDS = 20 * 60
_RETAIN_SECONDS = 24 * 60 * 60
_MAX_JOBS = 32


@dataclass
class _Reservation:
    job: PlaylistExportJob
    signal: AsyncSignal
    touched: float


class PlaylistExportRuntime:
    """Retain exact plans, confirmed job progress and duplicate-start protection."""

    def __init__(self, spotify: PlaylistGateway, jobs: JobTasks) -> None:
        """Bind shared Spotify access and background task ownership.

        Args:
            spotify: Named read and write authority for Spotify playlists.
            jobs: Lifespan task owner draining writes before shutdown.
        """
        self.spotify = spotify
        self._jobs = jobs
        self._records: dict[str, _Reservation] = {}

    def prepare(self, plan: ExportPlan) -> PlaylistExportJob:
        """Keep a plan ready for an explicit later confirmation.

        Args:
            plan: Exact additions and destination shown for review.

        Returns:
            The prepared job handle, holding no active Spotify operation.
        """
        self._prune()
        self._make_room()
        job = PlaylistExportJob(uuid4().hex, plan)
        register_job(
            self._records, job.job_id, _Reservation(job, AsyncSignal(), monotonic())
        )
        return job

    def get(self, identity: str) -> PlaylistExportJob:
        """Return the retained plan and observed job progress.

        Args:
            identity: The process-local review/job ID.

        Returns:
            The original immutable plan and latest observed progress.
        """
        return self._record(identity).job

    def start(self, identity: str) -> PlaylistExportJob:
        """Start or resume the exact prepared job, safely handling double submission.

        Args:
            identity: Previously prepared, authenticated review/job ID.

        Returns:
            The reserved job with its original additions and destination.
        """
        record = self._record(identity)
        job = record.job
        if job.stage not in {"prepared", "paused"}:
            return job
        require_slot(
            (item.job for item in self._records.values()),
            "Another Listening Explorer export is already running.",
        )
        self._require_clear_destination(job)
        record.signal.clear()
        record.touched = monotonic()
        old_stage = job.stage
        job.stage, job.message = "queued", "Spotify export queued."
        try:
            self._jobs.start(
                run_playlist_export(job, self.spotify, record.signal),
                record.signal,
                f"listening-export-{identity[:8]}",
            )
        except RuntimeError as error:
            job.stage = old_stage
            raise HTTPException(
                503, "The server is restarting. Try again shortly."
            ) from error
        return job

    def pause(self, identity: str) -> PlaylistExportJob:
        """Request a stop at the next safe write boundary.

        Args:
            identity: Previously confirmed export ID.

        Returns:
            The export, preserving the last attempted batch for reconciliation.
        """
        record = self._record(identity)
        if record.job.stage in {"queued", "running"}:
            record.signal.set()
        return record.job

    def _record(self, identity: str) -> _Reservation:
        self._prune()
        record = self._records.get(identity)
        if record is None:
            raise HTTPException(404, "This export expired or the app restarted.")
        return record

    def _require_clear_destination(self, job: PlaylistExportJob) -> None:
        for record in self._records.values():
            earlier = record.job
            if earlier is job or earlier.stage != "paused":
                continue
            if _shares_pending_destination(earlier, job):
                raise HTTPException(
                    409, "Recheck the earlier export before using this destination."
                )

    def _prune(self) -> None:
        now = monotonic()
        for identity, record in tuple(self._records.items()):
            if _expired(record, now):
                del self._records[identity]

    def _make_room(self) -> None:
        if len(self._records) < _MAX_JOBS:
            return
        for identity, record in self._records.items():
            if record.job.stage in {"prepared", "failed", "complete"}:
                del self._records[identity]
                return
        raise HTTPException(409, "Resolve an existing export before preparing another.")


def _expired(record: _Reservation, now: float) -> bool:
    if record.job.stage == "prepared":
        return now - record.touched > _REVIEW_SECONDS
    if record.job.stage in {"complete", "failed", "paused"}:
        return now - record.touched > _RETAIN_SECONDS
    return False


def _shares_pending_destination(
    earlier: PlaylistExportJob, proposed: PlaylistExportJob
) -> bool:
    target = proposed.plan.target
    if earlier.plan.target.account != target.account:
        return False
    if target.existing is None:
        return earlier.creation_pending and earlier.plan.target.name == target.name
    return (
        earlier.pending is not None
        and earlier.playlist is not None
        and earlier.playlist.identity == target.existing.identity
    )
