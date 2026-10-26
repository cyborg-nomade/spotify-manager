"""Explicit callbacks and wire presentation for RequeueForADreamWorker."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.retry_attempts import CheckedAttempts
from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
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
    """Execute one reconnectable job and present its accepted outcome.

    Args:
        context: Invocation-owned context.
        job_id: Invocation-owned job id.
        spotify: Invocation-owned spotify.
        playlist_id: Invocation-owned playlist id.
        dry_run: Invocation-owned dry run.

    Attributes:
        job: Resolved reconnectable job state.
        events: SDK event subscription retaining the original setter binding.
    """

    context: PlaylistContext
    job_id: str
    spotify: Spotify
    playlist_id: str
    dry_run: bool
    job: _BlastJob = field(init=False)
    events: SpotifyEvents = field(init=False)

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
        with self.context.lock:
            self.job.result.detail = message
            self.context.append(self.job, message)

    def sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _RequeueForADreamJobCancelledError

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        self.check()
        scopes = SpotifyRetries(self, self, 10, 3).attempts(description)
        return CheckedAttempts(scopes, self)

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="flush_requeue_for_a_dream")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Requeue for a Dream started"
            self.context.append(
                self.job,
                "Requeue for a Dream started in dry-run mode."
                if self.dry_run
                else "Requeue for a Dream started.",
            )
        self.events = SpotifyEvents(self.spotify)
        self.events.subscribe(self)

    def _execute(self) -> requeue_for_a_dream.RequeueForADreamSummary:
        summary = requeue_for_a_dream.flush_requeue_for_a_dream(
            self.spotify,
            self.playlist_id,
            dry_run=self.dry_run,
            echo=self,
            progress_callback=self,
            retry_call=self,
        )
        return summary

    def _completed(self, summary: requeue_for_a_dream.RequeueForADreamSummary) -> None:
        with self.context.lock:
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
        self.events.restore()
        with self.context.lock:
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Requeue for a Dream stopped safely. Rerun it to continue."
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
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            self.context.append(self.job, self.job.result.detail)

    def _spotify_failed(self, exc: SpotifyException) -> None:
        with self.context.lock:
            if exc.http_status == 429:
                retry_after = review_album_limits.get_retry_after_seconds(exc)
                retry_at = (
                    self.context.clock.now(UTC) + timedelta(seconds=retry_after)
                    if retry_after is not None
                    else None
                )
                self.job.result.status = "paused"
                self.job.result.retry_at = retry_at.isoformat() if retry_at else None
                self.job.result.detail = (
                    f"Spotify rate limit reached. "
                    f"{review_album_limits.format_retry_after(retry_after)}."
                )
            else:
                self.job.result.status = "failed"
                self.job.result.detail = str(exc)
            self.context.append(self.job, self.job.result.detail)

    def _failed(self, exc: requeue_for_a_dream.RequeueForADreamError) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Requeue for a Dream failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected Requeue for a Dream error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Requeue for a Dream error: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def _present_transition_detail(
        self, summary: requeue_for_a_dream.RequeueForADreamSummary
    ) -> None:
        if summary.action == "advance":
            verb = "would advance" if self.dry_run else "advanced"
            self.job.result.detail = (
                f"{verb.capitalize()} {summary.artist} from "
                f"{summary.source_release} to {summary.target_release}."
            )
        elif summary.action == "drop":
            verb = "would drop" if self.dry_run else "dropped"
            self.job.result.detail = (
                f"{verb.capitalize()} {summary.artist}"
                f" after the final eligible release."
            )
        elif summary.action == "empty":
            self.job.result.detail = "Requeue for a Dream is empty."
        else:
            self.job.result.detail = (
                f"Skipped {summary.artist or 'the playlist head'}: "
                f"{summary.reason or 'no safe transition was found'}."
            )
        if summary.target_track:
            self.context.append(
                self.job,
                f"Next track: {summary.target_track} ({summary.target_release}).",
            )
        self.context.append(self.job, self.job.result.detail)

    def check(self) -> None:
        """Observe the original retry cancellation boundary.

        Raises:
            RuntimeError: This job was cancelled.
        """
        if self.job.cancel_event.is_set():
            raise _RequeueForADreamJobCancelledError
