"""Explicit callbacks and wire presentation for NewWineWorker."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta
from typing import cast

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.wine import NewWinePendingChoice
from spotify_manager.interfaces.http.models.wine import NewWineReleaseOption
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.playlist_retry import RateLimitRetries
from spotify_manager.interfaces.http.presenters.wine import (
    new_wine_refill_result as _new_wine_refill_result,
)
from spotify_manager.interfaces.http.presenters.wine import (
    new_wine_track_result as _new_wine_track_result,
)
from spotify_manager.interfaces.http.workers.errors import _NewWineJobCancelledError
from spotify_manager.interfaces.operations import new_wine as new_wine
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.requests.new_wine import NewWineCallbacks
from spotify_manager.interfaces.requests.new_wine import NewWineStorage


@dataclass(kw_only=True)
class NewWineWorker:
    """Execute one reconnectable job with invocation-owned inputs.

    Args:
        options: Caller-owned options.
        context: Caller-owned context.
        job_id: Caller-owned job id.
        spotify: Caller-owned spotify.
        rate_limit_delay: Caller-owned rate limit delay.

    Attributes:
        job: Resolved reconnectable job state.
        events: SDK event subscription retaining the original setter binding.
    """

    options: NewWineOptions
    context: PlaylistContext
    job_id: str
    spotify: Spotify
    rate_limit_delay: int
    job: _BlastJob = field(init=False)
    events: SpotifyEvents = field(init=False)

    def run(self) -> None:
        """Execute one interactive New Wine flush as a reconnectable web job."""
        self._start()
        try:
            summary = self._execute()
        except _NewWineJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except (new_wine.NewWineError, SpotifyException) as exc:
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
            raise _NewWineJobCancelledError
        with self.context.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status

    def choose_release(
        self,
        source: new_wine.PlaylistTrack,
        candidates: tuple[new_wine.ReleaseCandidate, ...],
    ) -> str:
        """Present feature options and wait for this job's accepted choice.

        Args:
            source: Original routine-supplied source.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _NewWineJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.pending_choice = NewWinePendingChoice(
                artist=source.primary_artist_name,
                source_track=source.name,
                terminal_release=source.release.release_type in {"Album", "EP"},
                releases=self._new_wine_release_options(candidates),
            )
            self.job.result.status = "waiting"
            self.job.result.detail = (
                f"Choose a release for {source.primary_artist_name} after {source.name}"
            )
            self.context.append(self.job, self.job.result.detail)
        return await_submission(self.job.choice_event, self)

    def choose_endpoint(
        self,
        source: new_wine.PlaylistTrack,
        tracks: tuple[new_wine.ReleaseTrack, ...],
        current_index: int,
    ) -> str:
        """Ask where to place the artist after the final release.

        Args:
            source: Original routine-supplied source.
            tracks: Original routine-supplied tracks.
            current_index: Original routine-supplied current index.

        Returns:
            The original accepted routine callback result.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _NewWineJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.pending_choice = NewWinePendingChoice(
                kind="album_endpoint",
                artist=source.primary_artist_name,
                source_track=source.name,
                release=source.release.name,
                track_position=current_index + 1,
                total_tracks=len(tracks),
            )
            self.job.result.status = "waiting"
            self.job.result.detail = (
                f"Is {source.name} the last canonical track of {source.release.name}?"
            )
            self.context.append(self.job, self.job.result.detail)
        return await_submission(self.job.choice_event, EndpointSubmission(self))

    def sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _NewWineJobCancelledError

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        return RateLimitRetries(SpotifyRetries(self, self, 10, 3), self).attempts(
            description
        )

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="flush_new_wine")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "New Wine flush started"
            self.context.append(
                self.job,
                (
                    f"New Wine flush started"
                    f"{(' in dry-run mode' if self.options.dry_run else '')}."
                ),
            )
        self.events = SpotifyEvents(self.spotify)
        self.events.subscribe(self)

    def _execute(self) -> new_wine.FlushSummary:
        summary = new_wine.flush_new_wine(
            self.spotify,
            self.options,
            NewWineCallbacks(
                choose=self,
                endpoint=self,
                output=self,
                progress=self,
                retry=self,
            ),
            storage=NewWineStorage(),
        )
        return summary

    def _completed(self, summary: new_wine.FlushSummary) -> None:
        results = [_new_wine_track_result(result) for result in summary.results]
        with self.context.lock:
            self.job.result.status = "paused" if summary.paused else "completed"
            self.job.result.processed = summary.processed
            self.job.result.total = summary.total
            self.job.result.advanced = summary.advanced
            self.job.result.dropped = summary.dropped
            self.job.result.sent_to_sauvignon = summary.sent_to_sauvignon
            self.job.result.completed_singles = summary.completed_singles
            self.job.result.skipped = summary.skipped
            self.job.result.albums_unsaved = summary.albums_unsaved
            self.job.result.new_wine_results = results
            self.job.result.new_wine_refill = _new_wine_refill_result(summary.refill)
            self.job.result.pending_choice = None
            if summary.paused:
                self.job.result.detail = "New Wine flush paused. Progress was saved."
            else:
                unsave_label = "to unsave" if self.options.dry_run else "unsaved"
                self.job.result.detail = (
                    f"{summary.processed}/{summary.total} processed; "
                    f"{summary.advanced} advanced, {summary.dropped} dropped, "
                    f"{summary.sent_to_sauvignon} sent to Sauvignon, "
                    f"{summary.albums_unsaved} albums {unsave_label}."
                )
                self._append_refill_detail(summary)
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        self.events.restore()
        with self.context.lock:
            self.job.result.pending_choice = None
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.pending_choice = None
            self.job.result.retry_at = None
            self.job.result.detail = (
                "New Wine flush stopped. Progress was saved."
                if not self.options.dry_run
                else "New Wine dry run stopped."
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
            self.job.result.pending_choice = None
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
            self.job.result.pending_choice = None
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.context.append(self.job, self.job.result.detail)

    def _failed(self, exc: new_wine.NewWineError | SpotifyException) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.pending_choice = None
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"New Wine flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected New Wine flush error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.pending_choice = None
            self.job.result.detail = f"Unexpected New Wine error: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def consume(self) -> str | None:
        """Consume an accepted submission while holding the job lock.

        Returns:
            Original submitted value, or none while the job is waiting.

        Raises:
            RuntimeError: The job's original cancellation boundary stops execution.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _NewWineJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying release choice"
            self.context.append(self.job, f"Release choice received: {choice}.")
            return choice

    def _consume_endpoint_choice_reader(self) -> str | None:
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _NewWineJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying album endpoint choice"
            self.context.append(self.job, f"Endpoint choice received: {choice}.")
            return choice

    def _new_wine_release_options(
        self, candidates: tuple[new_wine.ReleaseCandidate, ...]
    ) -> list[NewWineReleaseOption]:
        entries: list[NewWineReleaseOption] = []
        for candidate in candidates:
            entries.append(
                NewWineReleaseOption(
                    spotify_id=candidate.spotify_id,
                    name=candidate.name,
                    release_type=candidate.release_type,
                    release_date=candidate.release_date,
                    total_tracks=candidate.total_tracks,
                    primary_artist_name=candidate.primary_artist_name,
                )
            )
        return entries

    def wait_for_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError, description: str
    ) -> None:
        """Wait at the job's original rate-limit boundary.

        Args:
            exc: Original operation context.
            description: Original operation context.
        """
        delay = max(1, exc.retry_after_seconds or self.rate_limit_delay)
        retry_at = self.context.clock.now(UTC) + timedelta(seconds=delay)
        message = (
            f"Spotify rate limit reached while {description}"
            f". Retrying automatically "
            f"{review_album_limits.format_retry_delay(delay)}."
        )
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.retry_at = retry_at.isoformat()
            self.job.result.detail = message
            self.context.append(self.job, message)
        self.sleep(delay)
        with self.context.lock:
            self.job.result.retry_at = None
            self.job.result.detail = f"Retrying {description}."
            self.context.append(self.job, self.job.result.detail)

    def _append_refill_detail(self, summary: new_wine.FlushSummary) -> None:
        if summary.refill is not None:
            self.job.result.detail = cast(str, self.job.result.detail) + (
                f" New Wine {summary.refill.before} -> {summary.refill.after}; "
                f"{summary.refill.added} pulled from Wine Cellar."
            )

    def retry_accepted(self) -> None:
        """Clear the original retry timestamp after a successful operation."""
        with self.context.lock:
            self.job.result.retry_at = None


@dataclass(frozen=True)
class EndpointSubmission:
    """Consume this job's canonical album endpoint response.

    Args:
        worker: Job owning its pending choice, lock and signal.
    """

    worker: NewWineWorker

    def consume(self) -> str | None:
        """Consume the original locked endpoint response.

        Returns:
            Original response or none while the job is waiting.
        """
        return self.worker._consume_endpoint_choice_reader()
