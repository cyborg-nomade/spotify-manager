"""Explicit callbacks and wire presentation for Queue3Worker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from threading import Lock
from typing import cast

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discovery import (
    Queue3ComposerPlaylistOption,
)
from spotify_manager.interfaces.http.models.discovery import Queue3PendingChoice
from spotify_manager.interfaces.http.models.discovery import Queue3ReleaseOption
from spotify_manager.interfaces.http.workers.errors import _Queue3JobCancelledError
from spotify_manager.interfaces.operations import new_wine as new_wine
from spotify_manager.interfaces.operations import queue_3 as queue_3
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import slow_listening as slow_listening


@dataclass(kw_only=True)
class Queue3Worker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlist_id: Explicit playlist id input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        annual_only: Explicit annual only input or adapter boundary.
        connection_failure: Explicit connection failure input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        _apply_queue_3_annual_summary: Explicit apply queue 3 annual summary input or
            adapter boundary.
        _apply_queue_3_flush_summary: Explicit apply queue 3 flush summary input or
            adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _queue_3_release_option: Explicit queue 3 release option input or adapter
            boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    playlist_id: str
    dry_run: bool
    annual_only: bool
    connection_failure: str
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    _apply_queue_3_annual_summary: Callable[
        [_BlastJob, queue_3.AnnualImportSummary], None
    ]
    _apply_queue_3_flush_summary: Callable[[_BlastJob, queue_3.FlushSummary], None]
    lock: Lock
    _queue_3_release_option: Callable[..., Queue3ReleaseOption]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    operation_name: str = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one Queue 3 operation as a reconnectable web job."""
        self._start()
        try:
            summary = self._execute()
        except _Queue3JobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except RequestException:
            self._connection_failed()
        except (queue_3.Queue3Error, SpotifyException) as exc:
            self._failed(exc)
        except Exception as exc:
            self._unexpected_failure(exc)
        else:
            self._completed(summary)
        finally:
            self._finish()

    def echo(self, message: str) -> None:
        """Present a routine message using this job's original log sink.

        Args:
            message: Original routine-supplied message.
        """
        with self.lock:
            self.job.result.detail = message
            self.append(self.job, message)

    def progress_callback(
        self, completed: int, total: int, progress_status: str
    ) -> None:
        """Publish routine progress and observe its cancellation boundary.

        Args:
            completed: Original routine-supplied completed.
            total: Original routine-supplied total.
            progress_status: Original routine-supplied progress status.
        """
        if self.job.cancel_event.is_set():
            raise _Queue3JobCancelledError
        with self.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status

    def wait_for_choice(self, detail: str) -> str:
        """Publish a waiting phase and consume the next accepted choice.

        Args:
            detail: Original routine-supplied detail.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _Queue3JobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.status = "waiting"
            self.job.result.detail = detail
            self.append(self.job, detail)
        return await_submission(self.job.choice_event, self._consume_wait_for_choice)

    def transition_reader(
        self,
        source: new_wine.PlaylistTrack,
        current: slow_listening.DiscographyRelease,
        following: slow_listening.DiscographyRelease,
    ) -> str:
        """Ask for confirmation of the original Queue 3 transition.

        Args:
            source: Original routine-supplied source.
            current: Original routine-supplied current.
            following: Original routine-supplied following.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            self.job.result.queue_3_pending_choice = Queue3PendingChoice(
                kind="release",
                artist=source.primary_artist_name,
                source_track=source.name,
                current_release=self._queue_3_release_option(current),
                next_release=self._queue_3_release_option(following),
            )
        return self.wait_for_choice(
            f"Confirm the next release for {source.primary_artist_name}"
        )

    def composer_playlist_reader(
        self, artist: str, candidates: tuple[queue_3.OwnedPlaylist, ...]
    ) -> str:
        """Present the original composer playlist options.

        Args:
            artist: Original routine-supplied artist.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            self.job.result.queue_3_pending_choice = Queue3PendingChoice(
                kind="composer_playlist",
                artist=artist,
                playlists=self._queue3_composer_playlist_options(candidates),
            )
        return self.wait_for_choice(f"Choose the composer playlist for {artist}")

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _Queue3JobCancelledError

    def retry_call(self, operation: Callable[[], object], description: str) -> object:
        """Apply the original retry policy with job-owned event callbacks.

        Args:
            operation: Original routine-supplied operation.
            description: Original routine-supplied description.

        Returns:
            The original accepted routine callback result.
        """
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self.echo,
            sleep=self.interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _start(self) -> None:
        self.job = self.lookup(self.job_id, command="flush_queue_3")
        self.operation_name = (
            "Previous-year Queue 3 import" if self.annual_only else "Queue 3 flush"
        )
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = f"{self.operation_name} started"
            self.append(
                self.job,
                (
                    f"{self.operation_name}"
                    " started"
                    f"{(' in dry-run mode' if self.dry_run else '')}"
                    "."
                ),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> queue_3.AnnualImportSummary | queue_3.FlushSummary:
        summary: queue_3.AnnualImportSummary | queue_3.FlushSummary
        if self.annual_only:
            summary = queue_3.import_previous_year_discoveries(
                self.spotify,
                self.playlist_id,
                dry_run=self.dry_run,
                echo=self.echo,
                progress_callback=self.progress_callback,
                retry_call=self.retry_call,
            )
        else:
            summary = queue_3.flush_queue_3(
                self.spotify,
                self.playlist_id,
                self.transition_reader,
                composer_playlist_reader=self.composer_playlist_reader,
                dry_run=self.dry_run,
                echo=self.echo,
                progress_callback=self.progress_callback,
                retry_call=self.retry_call,
            )
        return summary

    def _completed(
        self, summary: queue_3.AnnualImportSummary | queue_3.FlushSummary
    ) -> None:
        with self.lock:
            if isinstance(summary, queue_3.AnnualImportSummary):
                self._apply_queue_3_annual_summary(self.job, summary)
            else:
                self._apply_queue_3_flush_summary(self.job, summary)
            self.append(self.job, cast(str, self.job.result.detail))

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.queue_3_pending_choice = None
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            if self.annual_only:
                self.job.result.detail = "Previous-year Queue 3 import stopped."
            elif self.dry_run:
                self.job.result.detail = "Queue 3 dry run stopped."
            else:
                self.job.result.detail = "Queue 3 flush stopped. Progress was saved."
            self.append(self.job, self.job.result.detail)

    def _rate_limited(self, exc: review_album_limits.SpotifyRateLimitError) -> None:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = self.clock.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with self.lock:
            self.job.result.status = "paused"
            self.job.result.retry_at = retry_at.isoformat() if retry_at else None
            self.job.result.detail = (
                "Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                "."
            )
            self.append(self.job, self.job.result.detail)

    def _temporarily_unavailable(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> None:
        with self.lock:
            self.job.result.status = "paused"
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.append(self.job, self.job.result.detail)

    def _connection_failed(self) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.append(self.job, self.job.result.detail)

    def _failed(self, exc: queue_3.Queue3Error | SpotifyException) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"{self.operation_name} failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected %s error", self.operation_name)
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected {self.operation_name} error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _consume_wait_for_choice(self) -> str | None:
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _Queue3JobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.queue_3_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying Queue 3 choice"
            self.append(self.job, f"Queue 3 choice received: {choice}.")
            return choice

    def _queue3_composer_playlist_options(
        self, candidates: tuple[queue_3.OwnedPlaylist, ...]
    ) -> list[Queue3ComposerPlaylistOption]:
        entries: list[Queue3ComposerPlaylistOption] = []
        for candidate in candidates:
            entries.append(
                Queue3ComposerPlaylistOption(
                    spotify_id=candidate.spotify_id,
                    name=candidate.name,
                    total_tracks=candidate.total_tracks,
                )
            )
        return entries
