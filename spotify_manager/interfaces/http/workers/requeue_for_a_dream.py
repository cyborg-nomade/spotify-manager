"""Explicit callbacks and wire presentation for RequeueForADreamWorker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from threading import Lock

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.workers.errors import (
    _RequeueForADreamJobCancelledError,
)
from spotify_manager.interfaces.operations import (
    requeue_for_a_dream as requeue_for_a_dream,
)
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class RequeueForADreamWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlist_id: Explicit playlist id input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    playlist_id: str
    dry_run: bool
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one reconnectable Requeue for a Dream transition."""
        self._start()
        try:
            summary = self._execute()
        except _RequeueForADreamJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except SpotifyException as exc:
            self._spotify_failed(exc)
        except requeue_for_a_dream.RequeueForADreamError as exc:
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

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _RequeueForADreamJobCancelledError

    def retry_call(self, operation: Callable[[], object], description: str) -> object:
        """Apply the original retry policy with job-owned event callbacks.

        Args:
            operation: Original routine-supplied operation.
            description: Original routine-supplied description.

        Returns:
            The original accepted routine callback result.
        """
        if self.job.cancel_event.is_set():
            raise _RequeueForADreamJobCancelledError
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self.echo,
            sleep=self.interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        if self.job.cancel_event.is_set():
            raise _RequeueForADreamJobCancelledError
        return result

    def _start(self) -> None:
        self.job = self.lookup(self.job_id, command="flush_requeue_for_a_dream")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Requeue for a Dream started"
            self.append(
                self.job,
                "Requeue for a Dream started in dry-run mode."
                if self.dry_run
                else "Requeue for a Dream started.",
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> requeue_for_a_dream.RequeueForADreamSummary:
        summary = requeue_for_a_dream.flush_requeue_for_a_dream(
            self.spotify,
            self.playlist_id,
            dry_run=self.dry_run,
            echo=self.echo,
            progress_callback=self.echo,
            retry_call=self.retry_call,
        )
        return summary

    def _completed(self, summary: requeue_for_a_dream.RequeueForADreamSummary) -> None:
        with self.lock:
            self.job.result.status = "completed"
            self.job.result.requeue_action = summary.action
            self.job.result.requeue_artist = summary.artist
            self.job.result.requeue_source_track = summary.source_track
            self.job.result.requeue_source_release = summary.source_release
            self.job.result.requeue_target_track = summary.target_track
            self.job.result.requeue_target_release = summary.target_release
            self.job.result.requeue_target_release_type = summary.target_release_type
            self.job.result.requeue_target_release_date = summary.target_release_date
            self.job.result.requeue_target_already_present = (
                summary.target_already_present
            )
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = int(
                summary.action == "advance" and (not summary.target_already_present)
            )
            self._present_transition_detail(summary)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Requeue for a Dream stopped safely. Rerun it to continue."
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
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            self.append(self.job, self.job.result.detail)

    def _spotify_failed(self, exc: SpotifyException) -> None:
        with self.lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    self.clock.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                self.job.result.status = "paused"
                self.job.result.retry_at = retry_at.isoformat() if retry_at else None
                self.job.result.detail = (
                    "Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}"
                    "."
                )
            else:
                self.job.result.status = "failed"
                self.job.result.detail = str(exc)
            self.append(self.job, self.job.result.detail)

    def _failed(self, exc: requeue_for_a_dream.RequeueForADreamError) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"Requeue for a Dream failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected Requeue for a Dream error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Requeue for a Dream error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _present_transition_detail(
        self, summary: requeue_for_a_dream.RequeueForADreamSummary
    ) -> None:
        if summary.action == "advance":
            verb = "would advance" if self.dry_run else "advanced"
            self.job.result.detail = (
                f"{verb.capitalize()}"
                " "
                f"{summary.artist}"
                " from "
                f"{summary.source_release}"
                " to "
                f"{summary.target_release}"
                "."
            )
        elif summary.action == "drop":
            verb = "would drop" if self.dry_run else "dropped"
            self.job.result.detail = (
                f"{verb.capitalize()}"
                " "
                f"{summary.artist}"
                " after the final eligible release."
            )
        elif summary.action == "empty":
            self.job.result.detail = "Requeue for a Dream is empty."
        else:
            self.job.result.detail = (
                "Skipped "
                f"{summary.artist or 'the playlist head'}"
                ": "
                f"{summary.reason or 'no safe transition was found'}"
                "."
            )
        if summary.target_track:
            self.append(
                self.job,
                (f"Next track: {summary.target_track} ({summary.target_release})."),
            )
        self.append(self.job, self.job.result.detail)
