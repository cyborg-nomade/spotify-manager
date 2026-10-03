"""Explicit callbacks and wire presentation for QueueFillWorker."""

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

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.queue import QueueArtistOption
from spotify_manager.interfaces.http.models.queue import QueueFillResultEntry
from spotify_manager.interfaces.http.models.queue import QueuePendingChoice
from spotify_manager.interfaces.http.workers.errors import _QueueJobCancelledError
from spotify_manager.interfaces.operations import release_check as release_check
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import the_queue as the_queue


@dataclass(kw_only=True)
class QueueFillWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlists: Explicit playlists input or adapter boundary.
        api_key: Explicit api key input or adapter boundary.
        username: Explicit username input or adapter boundary.
        count: Explicit count input or adapter boundary.
        max_playlist_length: Explicit max playlist length input or adapter boundary.
        seed_count: Explicit seed count input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        create_lastfm: Explicit create lastfm input or adapter boundary.
        connection_failure: Explicit connection failure input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _queue_fill_result_entry: Explicit queue fill result entry input or adapter
            boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    playlists: the_queue.QueuePlaylists
    api_key: str
    username: str
    count: int | None
    max_playlist_length: int | None
    seed_count: int
    dry_run: bool
    create_lastfm: Callable[..., LastFmClient]
    connection_failure: str
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _queue_fill_result_entry: Callable[..., QueueFillResultEntry]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    last_progress: str | None = field(init=False, default=None)
    lastfm: LastFmClient = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

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
            self.job.result.total = total or None
            self.job.result.detail = progress_status
            if progress_status != self.last_progress:
                self.append(self.job, progress_status)
                self.last_progress = progress_status

    def choice_reader(
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
        with self.lock:
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
            self.append(self.job, self.job.result.detail)
        return await_submission(self.job.choice_event, self._consume_choice_reader)

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
        self.job = self.lookup(self.job_id, command="fill_queue_from_lastfm")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Queue artist discovery started"
            self.append(
                self.job,
                (
                    "Queue artist discovery started"
                    f"{(' in dry-run mode' if self.dry_run else '')}"
                    "."
                ),
            )
        self.last_progress: str | None = None
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)
        self.lastfm = self.create_lastfm(
            self.api_key, self.username, event_callback=self.echo
        )

    def _execute(self) -> the_queue.FillSummary:
        summary = the_queue.fill_queue_from_lastfm(
            self.spotify,
            self.lastfm,
            self.playlists,
            self.choice_reader,
            count=self.count,
            max_playlist_length=self.max_playlist_length,
            seed_count=self.seed_count,
            dry_run=self.dry_run,
            echo=self.echo,
            progress_callback=self.progress_callback,
            retry_call=self.retry_call,
        )
        return summary

    def _completed(self, summary: the_queue.FillSummary) -> None:
        results = [self._queue_fill_result_entry(result) for result in summary.results]
        with self.lock:
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
                    "Selected "
                    f"{summary.selected}"
                    " of "
                    f"{summary.requested_count}"
                    " artists; Queue "
                    f"{summary.playlist_length_before}"
                    " -> "
                    f"{summary.playlist_length_after}"
                    "."
                )
            )
            for result in results:
                self._log_result(result)
            self.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.queue_pending_choice = None
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                (
                    "Queue fill stopped. Cached calls and completed "
                    "additions remain saved."
                )
                if not self.dry_run
                else "Queue fill dry run stopped."
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
                + ". Cached calls and completed additions remain saved."
            )
            self.append(self.job, self.job.result.detail)

    def _connection_failed(self) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.append(self.job, self.job.result.detail)

    def _failed(
        self,
        exc: the_queue.QueueError
        | release_check.ReleaseCheckError
        | LastFmError
        | SpotifyException,
    ) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"Queue fill failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected Queue fill error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Queue fill error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _consume_choice_reader(self) -> str | None:
        with self.lock:
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
            self.append(self.job, f"Artist mapping choice received: {choice}.")
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
        self.append(self.job, f"{result.lastfm_artist} -> {target} ({result.action}).")
