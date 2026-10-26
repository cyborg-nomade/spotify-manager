"""Explicit callbacks and wire presentation for QueueFillWorker."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.queue import QueueArtistOption
from spotify_manager.interfaces.http.models.queue import QueueFillResultEntry
from spotify_manager.interfaces.http.models.queue import QueuePendingChoice
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.presenters.queue import (
    queue_fill_result_entry as _queue_fill_result_entry,
)
from spotify_manager.interfaces.http.workers.errors import _QueueJobCancelledError
from spotify_manager.interfaces.operations import release_check as release_check
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import the_queue as the_queue
from spotify_manager.interfaces.requests.queue_fill import QueueFillCallbacks
from spotify_manager.interfaces.requests.queue_fill import QueueFillOptions
from spotify_manager.interfaces.requests.queue_fill import QueueFillResources


@dataclass(kw_only=True)
class QueueFillWorker:
    """Execute one reconnectable job with invocation-owned inputs.

    Args:
        credentials: Caller-owned credentials.
        options: Caller-owned options.
        context: Caller-owned context.
        job_id: Caller-owned job id.
        spotify: Caller-owned spotify.
        connection_failure: Caller-owned connection failure.

    Attributes:
        job: Resolved reconnectable job state.
        last_progress: Most recently accepted progress description.
        lastfm: Invocation-owned Last.fm reader created at the original boundary.
        events: SDK event subscription retaining the original setter binding.
    """

    credentials: LastFmCredentials
    options: QueueFillOptions
    context: PlaylistContext
    job_id: str
    spotify: Spotify
    connection_failure: str
    job: _BlastJob = field(init=False)
    last_progress: str | None = field(init=False, default=None)
    lastfm: LastFmClient = field(init=False)
    events: SpotifyEvents = field(init=False)

    def run(self) -> None:
        """Run reconnectable Last.fm artist discovery for The Queue."""
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
        except (
            the_queue.QueueError,
            release_check.ReleaseCheckError,
            LastFmError,
            SpotifyException,
        ) as exc:
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
            self.job.result.total = total or None
            self.job.result.detail = progress_status
            if progress_status != self.last_progress:
                self.context.append(self.job, progress_status)
                self.last_progress = progress_status

    def choose_artist(
        self,
        recommendation: the_queue.ArtistRecommendation,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        """Present feature options and wait for this job's accepted choice.

        Args:
            recommendation: Original routine-supplied recommendation.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _QueueJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.queue_pending_choice = QueuePendingChoice(
                artist=recommendation.artist,
                base_rank=recommendation.base_rank,
                score=recommendation.score,
                supporting_seeds=list(recommendation.supporting_seeds),
                candidates=self._queue_artist_options(candidates),
            )
            self.job.result.status = "waiting"
            self.job.result.detail = f"Map Last.fm artist {recommendation.artist}"
            self.context.append(self.job, self.job.result.detail)
        return await_submission(self.job.choice_event, self)

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
        self.job = self.context.lookup(self.job_id, command="fill_queue_from_lastfm")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Queue artist discovery started"
            self.context.append(
                self.job,
                (
                    f"Queue artist discovery started"
                    f"{(' in dry-run mode' if self.options.dry_run else '')}."
                ),
            )
        self.last_progress: str | None = None
        self.events = SpotifyEvents(self.spotify)
        self.events.subscribe(self)
        self.lastfm = lastfm_client(
            LastFmCredentials(self.credentials.api_key, self.credentials.username),
            self,
        )

    def _execute(self) -> the_queue.FillSummary:
        summary = the_queue.fill_queue_from_lastfm(
            self.spotify,
            self.lastfm,
            self.options,
            QueueFillCallbacks(
                choice_reader=self,
                output=self,
                progress_callback=self,
                retry_call=self,
            ),
            QueueFillResources(),
        )
        return summary

    def _completed(self, summary: the_queue.FillSummary) -> None:
        results = [_queue_fill_result_entry(result) for result in summary.results]
        with self.context.lock:
            self.job.result.status = "paused" if summary.paused else "completed"
            self.job.result.requested_count = summary.requested_count
            self.job.result.week_start = summary.week_start.isoformat()
            self.job.result.history_scrobbles = summary.history_scrobbles
            self.job.result.queue_history_artists = summary.history_artists
            self.job.result.live_scrobbles_added = summary.live_scrobbles_added
            self.job.result.queue_seed_count = summary.seed_count
            self.job.result.candidate_count = summary.candidate_count
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = summary.selected
            self.job.result.queue_fill_results = results
            self.job.result.detail = (
                "Queue fill paused; rerun to continue."
                if summary.paused
                else (
                    f"Selected {summary.selected} of {summary.requested_count}"
                    f" artists; Queue {summary.playlist_length_before} -> "
                    f"{summary.playlist_length_after}."
                )
            )
            for result in results:
                self._log_result(result)
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        self.events.restore()
        with self.context.lock:
            self.job.result.queue_pending_choice = None
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Queue fill stopped. Cached calls and completed additions remain saved."
                if not self.options.dry_run
                else "Queue fill dry run stopped."
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
                + ". Cached calls and completed additions remain saved."
            )
            self.context.append(self.job, self.job.result.detail)

    def _connection_failed(self) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.context.append(self.job, self.job.result.detail)

    def _failed(
        self,
        exc: the_queue.QueueError
        | release_check.ReleaseCheckError
        | LastFmError
        | SpotifyException,
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Queue fill failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected Queue fill error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Queue fill error: {exc}"
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
                raise _QueueJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.queue_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying Queue artist mapping"
            self.context.append(self.job, f"Artist mapping choice received: {choice}.")
            return choice

    def _queue_artist_options(
        self, candidates: tuple[release_check.SpotifyArtistCandidate, ...]
    ) -> list[QueueArtistOption]:
        entries: list[QueueArtistOption] = []
        for candidate in candidates:
            entries.append(
                QueueArtistOption(
                    spotify_id=candidate.spotify_id,
                    name=candidate.name,
                    popularity=candidate.popularity,
                    followers=candidate.followers,
                    exact_name=candidate.exact_name,
                )
            )
        return entries

    def _log_result(self, result: QueueFillResultEntry) -> None:
        target = result.spotify_artist or "no Spotify mapping"
        if result.track:
            target += f" - {result.track}"
        self.context.append(
            self.job, f"{result.lastfm_artist} -> {target} ({result.action})."
        )
