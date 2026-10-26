"""Explicit callbacks and wire presentation for QueueFlushWorker."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.queue import QueueFlushResultEntry
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.presenters.queue import (
    queue_flush_result_entry as _queue_flush_result_entry,
)
from spotify_manager.interfaces.http.workers.errors import _QueueJobCancelledError
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import the_queue as the_queue


@dataclass(kw_only=True)
class QueueFlushWorker:
    """Execute one reconnectable job and present its accepted outcome.

    Args:
        context: Invocation-owned context.
        job_id: Invocation-owned job id.
        spotify: Invocation-owned spotify.
        playlists: Invocation-owned playlists.
        dry_run: Invocation-owned dry run.
        connection_failure: Invocation-owned connection failure.

    Attributes:
        job: Resolved reconnectable job state.
        last_progress: Most recently accepted progress description.
        events: SDK event subscription retaining the original setter binding.
    """

    context: PlaylistContext
    job_id: str
    spotify: Spotify
    playlists: the_queue.QueuePlaylists
    dry_run: bool
    connection_failure: str
    job: _BlastJob = field(init=False)
    last_progress: str | None = field(init=False, default=None)
    events: SpotifyEvents = field(init=False)

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
        with self.context.lock:
            self.job.result.detail = message
            self.context.append(self.job, message)

    def progress(self, completed: int, total: int, progress_status: str) -> None:
        """Publish routine progress and observe its cancellation boundary.

        Args:
            completed: Original routine-supplied completed.
            total: Original routine-supplied total.
            progress_status: Original routine-supplied progress status.
        """
        if self.job.cancel_event.is_set():
            raise _QueueJobCancelledError
        with self.context.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status
            if progress_status != self.last_progress:
                self.context.append(self.job, progress_status)
                self.last_progress = progress_status

    def sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _QueueJobCancelledError

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        return SpotifyRetries(self, self, 10, 3).attempts(description)

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="flush_queue")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Queue flush started"
            self.context.append(
                self.job,
                f"Queue flush started{(' in dry-run mode' if self.dry_run else '')}.",
            )
        self.last_progress: str | None = None
        self.events = SpotifyEvents(self.spotify)
        self.events.subscribe(self)

    def _execute(self) -> the_queue.FlushSummary:
        summary = the_queue.flush_queue(
            self.spotify,
            self.playlists,
            dry_run=self.dry_run,
            echo=self,
            progress_callback=self,
            retry_call=self,
        )
        return summary

    def _completed(self, summary: the_queue.FlushSummary) -> None:
        results = [_queue_flush_result_entry(result) for result in summary.results]
        with self.context.lock:
            self.job.result.status = "completed"
            self.job.result.run_id = summary.run_id
            self.job.result.processed = summary.processed
            self.job.result.total = summary.total
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.queue_resumed = summary.resumed
            self.job.result.queue_flush_results = results
            self.job.result.detail = (
                f"Processed {summary.processed} of {summary.total} artists; Queue "
                f"{summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                self._log_result(result)
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        self.events.restore()
        with self.context.lock:
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Queue flush stopped. Progress was saved."
                if not self.dry_run
                else "Queue flush dry run stopped."
            )
            self.context.append(self.job, self.job.result.detail)

    def _rate_limited(self, exc: review_album_limits.SpotifyRateLimitError) -> None:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = self.context.clock.now(UTC) + timedelta(
                seconds=exc.retry_after_seconds
            )
        with self.context.lock:
            self.job.result.status = "paused"
            self.job.result.retry_at = retry_at.isoformat() if retry_at else None
            self.job.result.detail = (
                f"Spotify rate limit reached. "
                f"{review_album_limits.format_retry_after(exc.retry_after_seconds)}"
                f"."
            )
            self.context.append(self.job, self.job.result.detail)

    def _temporarily_unavailable(
        self, exc: review_album_limits.SpotifyTransientServerError
    ) -> None:
        with self.context.lock:
            self.job.result.status = "paused"
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.context.append(self.job, self.job.result.detail)

    def _connection_failed(self) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.context.append(self.job, self.job.result.detail)

    def _failed(self, exc: the_queue.QueueError | SpotifyException) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Queue flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected Queue flush error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Queue flush error: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def _log_result(self, result: QueueFlushResultEntry) -> None:
        target = result.target_track or "no replacement"
        if result.target_release:
            target = f"{result.target_release} - {target}"
        self.context.append(
            self.job,
            (
                f"{result.artist}: {result.source_track} -> {target} ("
                f"{result.action}; top {result.top_liked_tracks}/"
                f"{result.top_tracks}; total {result.total_liked_tracks})."
            ),
        )
