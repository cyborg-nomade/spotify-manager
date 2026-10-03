"""Explicit callbacks and wire presentation for QueueFlushWorker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from threading import Lock

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.queue import QueueFlushResultEntry
from spotify_manager.interfaces.http.workers.errors import _QueueJobCancelledError
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import the_queue as the_queue


@dataclass(kw_only=True)
class QueueFlushWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlists: Explicit playlists input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        connection_failure: Explicit connection failure input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _queue_flush_result_entry: Explicit queue flush result entry input or adapter
            boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    playlists: the_queue.QueuePlaylists
    dry_run: bool
    connection_failure: str
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _queue_flush_result_entry: Callable[..., QueueFlushResultEntry]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    last_progress: str | None = field(init=False, default=None)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Run the first-ten-artist Queue flush as a reconnectable web job."""
        self._start()
        try:
            summary = self._execute()
        except _QueueJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except RequestException:
            self._connection_failed()
        except (the_queue.QueueError, SpotifyException) as exc:
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
            raise _QueueJobCancelledError
        with self.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status
            if progress_status != self.last_progress:
                self.append(self.job, progress_status)
                self.last_progress = progress_status

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _QueueJobCancelledError

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
        self.job = self.lookup(self.job_id, command="flush_queue")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Queue flush started"
            self.append(
                self.job,
                (f"Queue flush started{(' in dry-run mode' if self.dry_run else '')}."),
            )
        self.last_progress: str | None = None
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> the_queue.FlushSummary:
        summary = the_queue.flush_queue(
            self.spotify,
            self.playlists,
            dry_run=self.dry_run,
            echo=self.echo,
            progress_callback=self.progress_callback,
            retry_call=self.retry_call,
        )
        return summary

    def _completed(self, summary: the_queue.FlushSummary) -> None:
        results = [self._queue_flush_result_entry(result) for result in summary.results]
        with self.lock:
            self.job.result.status = "completed"
            self.job.result.run_id = summary.run_id
            self.job.result.processed = summary.processed
            self.job.result.total = summary.total
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.queue_resumed = summary.resumed
            self.job.result.queue_flush_results = results
            self.job.result.detail = (
                "Processed "
                f"{summary.processed}"
                " of "
                f"{summary.total}"
                " artists; Queue "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                "."
            )
            for result in results:
                self._log_result(result)
            self.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Queue flush stopped. Progress was saved."
                if not self.dry_run
                else "Queue flush dry run stopped."
            )
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

    def _failed(self, exc: the_queue.QueueError | SpotifyException) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"Queue flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected Queue flush error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Queue flush error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _log_result(self, result: QueueFlushResultEntry) -> None:
        target = result.target_track or "no replacement"
        if result.target_release:
            target = f"{result.target_release} - {target}"
        self.append(
            self.job,
            (
                f"{result.artist}"
                ": "
                f"{result.source_track}"
                " -> "
                f"{target}"
                " ("
                f"{result.action}"
                "; top "
                f"{result.top_liked_tracks}"
                "/"
                f"{result.top_tracks}"
                "; total "
                f"{result.total_liked_tracks}"
                ")."
            ),
        )
