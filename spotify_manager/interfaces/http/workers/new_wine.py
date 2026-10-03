"""Explicit callbacks and wire presentation for NewWineWorker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from threading import Lock
from typing import cast

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.wine import NewWinePendingChoice
from spotify_manager.interfaces.http.models.wine import NewWineRefillResult
from spotify_manager.interfaces.http.models.wine import NewWineReleaseOption
from spotify_manager.interfaces.http.models.wine import NewWineTrackResult
from spotify_manager.interfaces.http.workers.errors import _NewWineJobCancelledError
from spotify_manager.routines import new_wine
from spotify_manager.routines import review_album_limits


@dataclass(kw_only=True)
class NewWineWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        new_wine_playlist_id: Explicit new wine playlist id input or adapter boundary.
        sauvignon_playlist_id: Explicit sauvignon playlist id input or adapter boundary.
        wine_cellar_playlist_id: Explicit wine cellar playlist id input or adapter
            boundary.
        dry_run: Explicit dry run input or adapter boundary.
        no_discovery: Explicit no discovery input or adapter boundary.
        choose_album_endpoints: Explicit choose album endpoints input or adapter
            boundary.
        rate_limit_delay: Explicit rate limit delay input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _new_wine_refill_result: Explicit new wine refill result input or adapter
            boundary.
        _new_wine_track_result: Explicit new wine track result input or adapter
            boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    new_wine_playlist_id: str
    sauvignon_playlist_id: str
    wine_cellar_playlist_id: str
    dry_run: bool
    no_discovery: bool
    choose_album_endpoints: bool
    rate_limit_delay: int
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _new_wine_refill_result: Callable[..., NewWineRefillResult | None]
    _new_wine_track_result: Callable[..., NewWineTrackResult]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

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
            raise _NewWineJobCancelledError
        with self.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status

    def choice_reader(
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
        with self.lock:
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
            self.append(self.job, self.job.result.detail)
        return await_submission(self.job.choice_event, self._consume_choice_reader)

    def endpoint_choice_reader(
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
        with self.lock:
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
            self.append(self.job, self.job.result.detail)
        return await_submission(
            self.job.choice_event, self._consume_endpoint_choice_reader
        )

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _NewWineJobCancelledError

    def retry_call(self, operation: Callable[[], object], description: str) -> object:
        """Apply the original retry policy with job-owned event callbacks.

        Args:
            operation: Original routine-supplied operation.
            description: Original routine-supplied description.

        Returns:
            The original accepted routine callback result.
        """
        while True:
            try:
                result = review_album_limits.retry_spotify_server_errors(
                    operation,
                    description,
                    echo=self.echo,
                    sleep=self.interruptible_sleep,
                    retry_delay_seconds=10,
                    max_attempts=3,
                )
            except review_album_limits.SpotifyRateLimitError as exc:
                self._wait_for_rate_limit(exc, description)
                continue
            with self.lock:
                self.job.result.retry_at = None
            return result

    def _start(self) -> None:
        self.job = self.lookup(self.job_id, command="flush_new_wine")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "New Wine flush started"
            self.append(
                self.job,
                (
                    "New Wine flush started"
                    f"{(' in dry-run mode' if self.dry_run else '')}"
                    "."
                ),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> new_wine.FlushSummary:
        summary = new_wine.flush_new_wine(
            self.spotify,
            self.new_wine_playlist_id,
            self.sauvignon_playlist_id,
            choice_reader=self.choice_reader,
            endpoint_choice_reader=self.endpoint_choice_reader,
            choose_album_endpoints=self.choose_album_endpoints,
            wine_cellar_playlist_id=self.wine_cellar_playlist_id,
            no_discovery=self.no_discovery,
            dry_run=self.dry_run,
            echo=self.echo,
            progress_callback=self.progress_callback,
            retry_call=self.retry_call,
        )
        return summary

    def _completed(self, summary: new_wine.FlushSummary) -> None:
        results = [self._new_wine_track_result(result) for result in summary.results]
        with self.lock:
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
            self.job.result.new_wine_refill = self._new_wine_refill_result(
                summary.refill
            )
            self.job.result.pending_choice = None
            if summary.paused:
                self.job.result.detail = "New Wine flush paused. Progress was saved."
            else:
                unsave_label = "to unsave" if self.dry_run else "unsaved"
                self.job.result.detail = (
                    f"{summary.processed}"
                    "/"
                    f"{summary.total}"
                    " processed; "
                    f"{summary.advanced}"
                    " advanced, "
                    f"{summary.dropped}"
                    " dropped, "
                    f"{summary.sent_to_sauvignon}"
                    " sent to Sauvignon, "
                    f"{summary.albums_unsaved}"
                    " albums "
                    f"{unsave_label}"
                    "."
                )
                self._append_refill_detail(summary)
            self.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.pending_choice = None
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.pending_choice = None
            self.job.result.retry_at = None
            self.job.result.detail = (
                "New Wine flush stopped. Progress was saved."
                if not self.dry_run
                else "New Wine dry run stopped."
            )
            self.append(self.job, self.job.result.detail)

    def _rate_limited(self, exc: review_album_limits.SpotifyRateLimitError) -> None:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = self.clock.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with self.lock:
            self.job.result.status = "paused"
            self.job.result.pending_choice = None
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
            self.job.result.pending_choice = None
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.append(self.job, self.job.result.detail)

    def _failed(self, exc: new_wine.NewWineError | SpotifyException) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.pending_choice = None
            self.job.result.detail = str(exc)
            self.append(self.job, f"New Wine flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected New Wine flush error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.pending_choice = None
            self.job.result.detail = f"Unexpected New Wine error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _consume_choice_reader(self) -> str | None:
        with self.lock:
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
            self.append(self.job, f"Release choice received: {choice}.")
            return choice

    def _consume_endpoint_choice_reader(self) -> str | None:
        with self.lock:
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
            self.append(self.job, f"Endpoint choice received: {choice}.")
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

    def _wait_for_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError, description: str
    ) -> None:
        delay = max(1, exc.retry_after_seconds or self.rate_limit_delay)
        retry_at = self.clock.now(UTC) + timedelta(seconds=delay)
        message = (
            "Spotify rate limit reached while "
            f"{description}"
            ". Retrying automatically "
            f"{review_album_limits.format_retry_delay(delay)}"
            "."
        )
        with self.lock:
            self.job.result.status = "running"
            self.job.result.retry_at = retry_at.isoformat()
            self.job.result.detail = message
            self.append(self.job, message)
        self.interruptible_sleep(delay)
        with self.lock:
            self.job.result.retry_at = None
            self.job.result.detail = f"Retrying {description}."
            self.append(self.job, self.job.result.detail)

    def _append_refill_detail(self, summary: new_wine.FlushSummary) -> None:
        if summary.refill is not None:
            self.job.result.detail = cast(str, self.job.result.detail) + (
                " New Wine "
                f"{summary.refill.before}"
                " -> "
                f"{summary.refill.after}"
                "; "
                f"{summary.refill.added}"
                " pulled from Wine Cellar."
            )
