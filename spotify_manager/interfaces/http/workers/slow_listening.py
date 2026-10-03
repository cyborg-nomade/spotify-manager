"""Explicit callbacks and wire presentation for SlowListeningWorker."""

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

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningPendingChoice,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningReleaseOption,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningTrackResult,
)
from spotify_manager.interfaces.http.presenters.collections import present_entries
from spotify_manager.interfaces.http.workers.errors import (
    _SlowListeningJobCancelledError,
)
from spotify_manager.routines import new_wine
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import slow_listening


@dataclass(kw_only=True)
class SlowListeningWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlist_id: Explicit playlist id input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _slow_listening_track_result: Explicit slow listening track result input or
            adapter boundary.
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
    _slow_listening_track_result: Callable[..., SlowListeningTrackResult]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute an interactive Slow Listening flush as a reconnectable job."""
        self._start()
        try:
            summary = self._execute()
        except _SlowListeningJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except (slow_listening.SlowListeningError, SpotifyException) as exc:
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
            raise _SlowListeningJobCancelledError
        with self.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status

    def wait_for_submission(
        self, pending: SlowListeningPendingChoice, detail: str
    ) -> tuple[str, tuple[str, ...] | None]:
        """Publish pending interaction data and consume its submission.

        Args:
            pending: Original routine-supplied pending.
            detail: Original routine-supplied detail.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _SlowListeningJobCancelledError
            self.job.submitted_choice = None
            self.job.submitted_order = None
            self.job.choice_event.clear()
            self.job.result.slow_listening_pending_choice = pending
            self.job.result.status = "waiting"
            self.job.result.detail = detail
            self.append(self.job, detail)
        return await_submission(
            self.job.choice_event, self._consume_wait_for_submission
        )

    def action_reader(
        self,
        source: new_wine.PlaylistTrack,
        target: new_wine.ReleaseTrack,
        target_release: slow_listening.DiscographyRelease,
    ) -> str:
        """Ask whether to add the proposed Slow Listening track.

        Args:
            source: Original routine-supplied source.
            target: Original routine-supplied target.
            target_release: Original routine-supplied target release.

        Returns:
            The original accepted routine callback result.
        """
        choice, _order = self.wait_for_submission(
            SlowListeningPendingChoice(
                kind="track",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
                target_track=target.name,
                target_release=target_release.name,
            ),
            (
                "Add "
                f"{target.name}"
                " ("
                f"{target_release.name}"
                ") after "
                f"{source.primary_artist_name}"
                " - "
                f"{source.name}"
                "?"
            ),
        )
        return choice

    def order_reader(
        self,
        release_date: str,
        candidates: tuple[slow_listening.DiscographyRelease, ...],
    ) -> tuple[str, ...]:
        """Read the submitted release order without changing its validation.

        Args:
            release_date: Original routine-supplied release date.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        artist = candidates[0].primary_artist_name if candidates else "Artist"
        choice, order = self.wait_for_submission(
            SlowListeningPendingChoice(
                kind="release_order",
                artist=artist,
                release_date=release_date,
                releases=self._slow_listening_release_options(candidates),
            ),
            (f"Order {artist}'s releases dated {release_date}."),
        )
        if choice != "order" or order is None:
            raise slow_listening.SlowListeningError(
                "Slow Listening release order was not submitted."
            )
        return order

    def completion_notifier(self, source: new_wine.PlaylistTrack) -> None:
        """Wait for acknowledgement of the completed artist.

        Args:
            source: Original routine-supplied source.
        """
        choice, _order = self.wait_for_submission(
            SlowListeningPendingChoice(
                kind="completion",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
            ),
            (
                f"{source.primary_artist_name}"
                " completed Slow Listening. Add a replacement "
                "artist, then continue."
            ),
        )
        if choice != "continue":
            raise slow_listening.SlowListeningError(
                "Slow Listening completion was not acknowledged."
            )

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _SlowListeningJobCancelledError

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
        self.job = self.lookup(self.job_id, command="flush_slow_listening")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Slow Listening flush started"
            self.append(
                self.job,
                (
                    "Slow Listening flush started"
                    f"{(' in dry-run mode' if self.dry_run else '')}"
                    "."
                ),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> slow_listening.FlushSummary:
        summary = slow_listening.flush_slow_listening(
            self.spotify,
            self.playlist_id,
            order_reader=self.order_reader,
            completion_notifier=self.completion_notifier,
            action_reader=self.action_reader,
            dry_run=self.dry_run,
            echo=self.echo,
            progress_callback=self.progress_callback,
            retry_call=self.retry_call,
        )
        return summary

    def _completed(self, summary: slow_listening.FlushSummary) -> None:
        results = present_entries(summary.results, self._slow_listening_track_result)
        with self.lock:
            self.job.result.status = "paused" if summary.paused else "completed"
            self.job.result.processed = summary.processed
            self.job.result.total = summary.total
            self.job.result.advanced = summary.advanced
            self.job.result.completed_artists = summary.completed_artists
            self.job.result.skipped = summary.skipped
            self.job.result.slow_listening_results = results
            self.job.result.slow_listening_pending_choice = None
            if summary.paused:
                self.job.result.detail = (
                    "Slow Listening flush paused. Progress was saved."
                )
            else:
                self.job.result.detail = (
                    f"{summary.processed}"
                    "/"
                    f"{summary.total}"
                    " processed; "
                    f"{summary.advanced}"
                    " advanced, "
                    f"{summary.completed_artists}"
                    " artists completed, "
                    f"{summary.skipped}"
                    " skipped."
                )
            self.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.slow_listening_pending_choice = None
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = (
                "Slow Listening flush stopped. Progress was saved."
                if not self.dry_run
                else "Slow Listening dry run stopped."
            )
            self.append(self.job, self.job.result.detail)

    def _rate_limited(self, exc: review_album_limits.SpotifyRateLimitError) -> None:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = self.clock.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with self.lock:
            self.job.result.status = "paused"
            self.job.result.slow_listening_pending_choice = None
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
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.append(self.job, self.job.result.detail)

    def _failed(
        self, exc: slow_listening.SlowListeningError | SpotifyException
    ) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = str(exc)
            self.append(self.job, f"Slow Listening flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected Slow Listening flush error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = f"Unexpected Slow Listening error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _consume_wait_for_submission(self) -> tuple[str, tuple[str, ...] | None] | None:
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _SlowListeningJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            order = self.job.submitted_order
            self.job.submitted_choice = None
            self.job.submitted_order = None
            self.job.choice_event.clear()
            self.job.result.slow_listening_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying Slow Listening choice"
            self.append(self.job, f"Slow Listening choice received: {choice}.")
            return (choice, order)

    def _slow_listening_release_options(
        self, candidates: tuple[slow_listening.DiscographyRelease, ...]
    ) -> list[SlowListeningReleaseOption]:
        entries: list[SlowListeningReleaseOption] = []
        for candidate in candidates:
            entries.append(
                SlowListeningReleaseOption(
                    spotify_id=candidate.spotify_id,
                    name=candidate.name,
                    release_type=candidate.release_type,
                    release_date=candidate.release_date,
                    total_tracks=candidate.total_tracks,
                    saved=candidate.saved,
                    plain=candidate.plain,
                )
            )
        return entries
