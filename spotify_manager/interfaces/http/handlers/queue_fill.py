"""Original queue fill HTTP validation and job interactions."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException
from spotipy import Spotify

from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.queue import QueueChoiceRequest
from spotify_manager.interfaces.http.validation import option_ids
from spotify_manager.routines import found_art
from spotify_manager.routines import the_queue
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class QueueFillHandlers:
    """Validate and present one feature through explicit facade dependencies.

    Args:
        Settings: Existing overridable feature dependency.
        _active_playlist_jobs: Existing overridable feature dependency.
        _blast_job_snapshot: Existing overridable feature dependency.
        _blast_jobs_lock: Existing overridable feature dependency.
        _cancel_queue_job: Existing overridable feature dependency.
        _configured_queue_playlists: Existing overridable feature dependency.
        get_blast_job: Existing overridable feature dependency.
        start_queue_fill_job: Existing overridable feature dependency.
    """

    Settings: type[Settings]
    _active_playlist_jobs: Callable[..., list[BlastJobResult]]
    _blast_job_snapshot: Callable[..., BlastJobResult]
    _blast_jobs_lock: Lock
    _cancel_queue_job: Callable[..., BlastJobResult]
    _configured_queue_playlists: Callable[..., the_queue.QueuePlaylists]
    get_blast_job: Callable[..., _BlastJob]
    start_queue_fill_job: Callable[..., BlastJobResult]

    def cmd_fill_queue_from_lastfm(
        self,
        client: Spotify,
        count: int | None,
        max_playlist_length: int | None,
        seed_count: int,
        dry_run: bool,
    ) -> BlastJobResult:
        """Start reconnectable Last.fm artist discovery for The Queue.

        Args:
            client: Original validated client value.
            count: Original validated count value.
            max_playlist_length: Original validated max playlist length value.
            seed_count: Original validated seed count value.
            dry_run: Original validated dry run value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        if count is not None and max_playlist_length is not None:
            raise HTTPException(
                status_code=400,
                detail=("use either count or maximum playlist length, not both"),
            )
        configuration = self.Settings()
        playlists = self._configured_queue_playlists()
        try:
            api_key, username = found_art.validate_lastfm_configuration(
                configuration.lastfm_api_key, configuration.lastfm_username
            )
        except found_art.FoundArtConfigError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        effective_count = (
            the_queue.DEFAULT_COUNT
            if count is None and max_playlist_length is None
            else count
        )
        return self.start_queue_fill_job(
            client,
            playlists,
            api_key,
            username,
            count=effective_count,
            max_playlist_length=max_playlist_length,
            seed_count=seed_count,
            dry_run=dry_run,
        )

    def cmd_active_queue_fill_jobs(self) -> list[BlastJobResult]:
        """Return active Queue fill jobs so the UI can reconnect after reload.

        Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._active_playlist_jobs("fill_queue_from_lastfm")

    def cmd_queue_fill_job(self, job_id: str) -> BlastJobResult:
        """Return Queue fill progress and any pending artist mapping.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        job = self.get_blast_job(job_id, command="fill_queue_from_lastfm")
        with self._blast_jobs_lock:
            return self._blast_job_snapshot(job)

    def cmd_choose_queue_artist(
        self, job_id: str, request: QueueChoiceRequest
    ) -> BlastJobResult:
        """Submit one Spotify artist mapping, custom search, skip, or quit.

        Args:
            job_id: Original validated job id value.
            request: Original validated request value.

            Returns:
            Original feature response with unchanged fields and validation.

            Raises:
            HTTPException: An original validation or feature error is observed.
        """
        job = self.get_blast_job(job_id, command="fill_queue_from_lastfm")
        with self._blast_jobs_lock:
            pending = job.result.queue_pending_choice
            if job.result.status != "waiting" or pending is None:
                raise HTTPException(
                    status_code=409,
                    detail=("Queue fill is not waiting for an artist mapping"),
                )
            allowed = {
                the_queue.CHOICE_SKIP,
                the_queue.CHOICE_QUIT,
                *option_ids(pending.candidates),
            }
            custom_search = request.choice.startswith(the_queue.CHOICE_SEARCH_PREFIX)
            if custom_search:
                custom_search = bool(
                    request.choice.removeprefix(the_queue.CHOICE_SEARCH_PREFIX).strip()
                )
            if request.choice not in allowed and (not custom_search):
                raise HTTPException(
                    status_code=400, detail=("artist choice is not available")
                )
            job.submitted_choice = request.choice
            job.result.queue_pending_choice = None
            job.result.status = "running"
            job.result.detail = "Queue artist choice submitted"
            job.choice_event.set()
            return self._blast_job_snapshot(job)

    def cmd_cancel_queue_fill_job(self, job_id: str) -> BlastJobResult:
        """Stop Queue artist discovery at its next safe boundary.

        Args:
            job_id: Original validated job id value.

            Returns:
            Original feature response with unchanged fields and validation.
        """
        return self._cancel_queue_job(job_id, "fill_queue_from_lastfm", "Queue fill")
