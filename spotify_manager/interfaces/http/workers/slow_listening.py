"""Explicit callbacks and wire presentation for SlowListeningWorker."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta

from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningPendingChoice,
)
from spotify_manager.interfaces.http.models.slow_listening import (
    SlowListeningReleaseOption,
)
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.presenters.slow_listening import (
    slow_listening_track_results,
)
from spotify_manager.interfaces.http.workers.errors import (
    _SlowListeningJobCancelledError,
)
from spotify_manager.interfaces.operations import new_wine as new_wine
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import slow_listening as slow_listening


@dataclass(kw_only=True)
class SlowListeningWorker:
    """Execute one reconnectable job and present its accepted outcome.

    Args:
        context: Shared job lock, clock and presentation context.
        job_id: Job id supplied by the caller.
        spotify: Caller-owned Spotify client.
        playlist_id: Destination playlist identity.
        dry_run: Whether to preview without durable writes.
        job: Mutable job record owned by this worker.

    Attributes:
        events: SDK event subscription retaining the original setter binding.
    """

    context: PlaylistContext
    job_id: str
    spotify: Spotify
    playlist_id: str
    dry_run: bool
    job: _BlastJob = field(init=False)
    events: SpotifyEvents = field(init=False)

    async def run(self) -> None:
        """Execute an interactive Slow Listening flush as a reconnectable job."""
        self._start()
        try:
            summary = await self._execute()
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
            raise _SlowListeningJobCancelledError
        with self.context.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status

    async def wait_for_submission(
        self, pending: SlowListeningPendingChoice, detail: str
    ) -> tuple[str, tuple[str, ...] | None]:
        """Publish pending interaction data and consume its submission.

        Args:
            pending: Original routine-supplied pending.
            detail: Original routine-supplied detail.

        Returns:
            The original accepted routine callback result.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _SlowListeningJobCancelledError
            self.job.submitted_choice = None
            self.job.submitted_order = None
            self.job.choice_event.clear()
            self.job.result.slow_listening_pending_choice = pending
            self.job.result.status = "waiting"
            self.job.result.detail = detail
            self.context.append(self.job, detail)
        return await await_submission(self.job.choice_event, self)

    async def choose_track(
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
        choice, _order = await self.wait_for_submission(
            SlowListeningPendingChoice(
                kind="track",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
                target_track=target.name,
                target_release=target_release.name,
            ),
            (
                f"Add {target.name} ({target_release.name}) after "
                f"{source.primary_artist_name} - {source.name}?"
            ),
        )
        return choice

    async def order_releases(
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
        choice, order = await self.wait_for_submission(
            SlowListeningPendingChoice(
                kind="release_order",
                artist=artist,
                release_date=release_date,
                releases=self._slow_listening_release_options(candidates),
            ),
            f"Order {artist}'s releases dated {release_date}.",
        )
        if choice != "order" or order is None:
            raise slow_listening.SlowListeningError(
                "Slow Listening release order was not submitted."
            )
        return order

    async def complete(self, source: new_wine.PlaylistTrack) -> None:
        """Wait for acknowledgement of the completed artist.

        Args:
            source: Original routine-supplied source.
        """
        choice, _order = await self.wait_for_submission(
            SlowListeningPendingChoice(
                kind="completion",
                artist=source.primary_artist_name,
                source_track=source.name,
                source_release=source.release.name,
            ),
            (
                f"{source.primary_artist_name}"
                f" completed Slow Listening. Add a replacement artist, then "
                f"continue."
            ),
        )
        if choice != "continue":
            raise slow_listening.SlowListeningError(
                "Slow Listening completion was not acknowledged."
            )

    async def sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if await self.job.cancel_event.wait(seconds):
            raise _SlowListeningJobCancelledError

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        return SpotifyRetries(self, self, 10, 3).attempts(description)

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="flush_slow_listening")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Slow Listening flush started"
            self.context.append(
                self.job,
                (
                    f"Slow Listening flush started"
                    f"{(' in dry-run mode' if self.dry_run else '')}."
                ),
            )
        self.events = SpotifyEvents(self.spotify)
        self.events.subscribe(self)

    async def _execute(self) -> slow_listening.FlushSummary:
        summary = await slow_listening.flush_slow_listening(
            self.spotify,
            self.playlist_id,
            order_reader=self,
            completion_notifier=self,
            action_reader=self,
            dry_run=self.dry_run,
            echo=self,
            progress_callback=self,
            retry_call=self,
        )
        return summary

    def _completed(self, summary: slow_listening.FlushSummary) -> None:
        results = slow_listening_track_results(summary.results)
        with self.context.lock:
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
                    f"{summary.processed}/{summary.total} processed; "
                    f"{summary.advanced} advanced, {summary.completed_artists}"
                    f" artists completed, {summary.skipped} skipped."
                )
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        self.events.restore()
        with self.context.lock:
            self.job.result.slow_listening_pending_choice = None
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = (
                "Slow Listening flush stopped. Progress was saved."
                if not self.dry_run
                else "Slow Listening dry run stopped."
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
            self.job.result.slow_listening_pending_choice = None
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
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.context.append(self.job, self.job.result.detail)

    def _failed(
        self, exc: slow_listening.SlowListeningError | SpotifyException
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Slow Listening flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected Slow Listening flush error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.slow_listening_pending_choice = None
            self.job.result.detail = f"Unexpected Slow Listening error: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def consume(self) -> tuple[str, tuple[str, ...] | None] | None:
        """Consume an accepted submission while holding the job lock.

        Returns:
            Original submitted value, or none while the job is waiting.

        Raises:
            RuntimeError: The job's original cancellation boundary stops execution.
        """
        with self.context.lock:
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
            self.context.append(self.job, f"Slow Listening choice received: {choice}.")
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
