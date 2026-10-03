"""Explicit callbacks and wire presentation for NewKidsWorker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from threading import Lock
from typing import Literal

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discovery import NewKidsFillResult
from spotify_manager.interfaces.http.models.discovery import NewKidsPendingChoice
from spotify_manager.interfaces.http.models.discovery import NewKidsReleaseOption
from spotify_manager.interfaces.http.models.discovery import NewKidsTrackResult
from spotify_manager.interfaces.http.presenters.collections import present_entries
from spotify_manager.interfaces.http.workers.errors import _NewKidsJobCancelledError
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import new_kids as new_kids
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.routines import composer_playlists
from spotify_manager.settings import Settings


@dataclass(kw_only=True)
class NewKidsWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        new_kids_playlist_id: Explicit new kids playlist id input or adapter boundary.
        queue_2_playlist_id: Explicit queue 2 playlist id input or adapter boundary.
        great_discoveries_playlist_id: Explicit great discoveries playlist id input or
            adapter boundary.
        unlucky_ones_playlist_id: Explicit unlucky ones playlist id input or adapter
            boundary.
        newfoundland_playlist_id: Explicit newfoundland playlist id input or adapter
            boundary.
        dry_run: Explicit dry run input or adapter boundary.
        command: Explicit command input or adapter boundary.
        rate_limit_delay: Explicit rate limit delay input or adapter boundary.
        create_lastfm: Explicit create lastfm input or adapter boundary.
        connection_failure: Explicit connection failure input or adapter boundary.
        configuration: Explicit configuration input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _new_kids_fill_result: Explicit new kids fill result input or adapter boundary.
        _new_kids_track_result: Explicit new kids track result input or adapter
            boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    new_kids_playlist_id: str
    queue_2_playlist_id: str
    great_discoveries_playlist_id: str
    unlucky_ones_playlist_id: str
    newfoundland_playlist_id: str
    dry_run: bool
    command: Literal["flush_new_kids", "flush_queue_2"]
    rate_limit_delay: int
    create_lastfm: Callable[..., LastFmClient]
    connection_failure: str
    configuration: Callable[[], Settings]
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _new_kids_fill_result: Callable[..., NewKidsFillResult]
    _new_kids_track_result: Callable[..., NewKidsTrackResult]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    label: str = field(init=False)
    lastfm: LastFmClient = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one interactive album-discovery flush as a reconnectable job."""
        self._start()
        try:
            summary = self._execute()
        except _NewKidsJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except RequestException:
            self._connection_failed()
        except (
            new_kids.NewKidsError,
            found_art.FoundArtConfigError,
            scrobble_history.ScrobbleHistoryError,
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
            raise _NewKidsJobCancelledError
        with self.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status

    def choice_reader(
        self, artist: str, candidates: tuple[new_kids.ChoiceCandidate, ...]
    ) -> str:
        """Present feature options and wait for this job's accepted choice.

        Args:
            artist: Original routine-supplied artist.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _NewKidsJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.new_kids_pending_choice = NewKidsPendingChoice(
                artist=artist, releases=self._new_kids_release_options(candidates)
            )
            self.job.result.status = "waiting"
            self.job.result.detail = f"Choose the next release for {artist}"
            self.append(self.job, self.job.result.detail)
        return await_submission(self.job.choice_event, self._consume_choice_reader)

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _NewKidsJobCancelledError

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
        self.label = "Queue 2" if self.command == "flush_queue_2" else "New Kids"
        self.job = self.lookup(self.job_id, command=self.command)
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = f"{self.label} flush started"
            self.append(
                self.job,
                (
                    f"{self.label}"
                    " flush started"
                    f"{(' in dry-run mode' if self.dry_run else '')}"
                    "."
                ),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> new_kids.FlushSummary | new_kids.Queue2Summary:
        configuration = self.configuration()
        lastfm_api_key, lastfm_username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
        self.lastfm = self.create_lastfm(
            lastfm_api_key, lastfm_username, event_callback=self.echo
        )
        routine = (
            new_kids.flush_queue_2
            if self.command == "flush_queue_2"
            else new_kids.flush_new_kids
        )
        summary = routine(
            self.spotify,
            self.new_kids_playlist_id,
            self.queue_2_playlist_id,
            self.great_discoveries_playlist_id,
            self.unlucky_ones_playlist_id,
            self.newfoundland_playlist_id,
            choice_reader=self.choice_reader,
            dry_run=self.dry_run,
            echo=self.echo,
            progress_callback=self.progress_callback,
            retry_call=self.retry_call,
            lastfm=self.lastfm,
            lastfm_username=lastfm_username,
        )
        return summary

    def _completed(
        self, summary: new_kids.FlushSummary | new_kids.Queue2Summary
    ) -> None:
        results = [self._new_kids_track_result(result) for result in summary.results]
        with self.lock:
            self.job.result.status = "paused" if summary.paused else "completed"
            self.job.result.processed = len(summary.results)
            if self.job.result.total is None:
                self.job.result.total = len(summary.results)
            if isinstance(summary, new_kids.Queue2Summary):
                self.job.result.playlist_length_before = summary.queue_length_before
                self.job.result.playlist_length_after = summary.queue_length_after
            else:
                self.job.result.playlist_length_before = summary.playlist_length_before
                self.job.result.playlist_length_after = summary.playlist_length_after
            self._present_transfers(summary, results)
            self._present_completion_detail(summary)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.new_kids_pending_choice = None
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.new_kids_pending_choice = None
            self.job.result.retry_at = None
            self.job.result.detail = (
                (f"{self.label} flush stopped. Progress was saved.")
                if not self.dry_run
                else (f"{self.label} dry run stopped.")
            )
            self.append(self.job, self.job.result.detail)

    def _rate_limited(self, exc: review_album_limits.SpotifyRateLimitError) -> None:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = self.clock.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with self.lock:
            self.job.result.status = "paused"
            self.job.result.new_kids_pending_choice = None
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
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.append(self.job, self.job.result.detail)

    def _connection_failed(self) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = self.connection_failure
            self.append(self.job, self.job.result.detail)

    def _failed(
        self,
        exc: new_kids.NewKidsError
        | found_art.FoundArtConfigError
        | scrobble_history.ScrobbleHistoryError
        | LastFmError
        | SpotifyException,
    ) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = str(exc)
            self.append(self.job, f"{self.label} flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected %s flush error", self.label)
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = f"Unexpected {self.label} error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _consume_choice_reader(self) -> str | None:
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _NewKidsJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.new_kids_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying release choice"
            self.append(self.job, f"Release choice received: {choice}.")
            return choice

    def _new_kids_release_options(
        self, candidates: tuple[new_kids.ChoiceCandidate, ...]
    ) -> list[NewKidsReleaseOption]:
        entries: list[NewKidsReleaseOption] = []
        for candidate in candidates:
            entries.append(
                NewKidsReleaseOption(
                    spotify_id=candidate.spotify_id,
                    name=candidate.name,
                    release_type="Composer works playlist"
                    if isinstance(candidate, composer_playlists.OwnedPlaylist)
                    else candidate.release_type,
                    release_date="Stored Spotify order"
                    if isinstance(candidate, composer_playlists.OwnedPlaylist)
                    else candidate.release_date,
                    total_tracks=candidate.total_tracks,
                    popularity=None
                    if isinstance(candidate, composer_playlists.OwnedPlaylist)
                    else candidate.popularity,
                    top_track_rank=None
                    if isinstance(candidate, composer_playlists.OwnedPlaylist)
                    else candidate.top_track_rank,
                    saved=False
                    if isinstance(candidate, composer_playlists.OwnedPlaylist)
                    else candidate.saved,
                )
            )
        return entries

    def _present_transfers(
        self,
        summary: new_kids.FlushSummary | new_kids.Queue2Summary,
        results: list[NewKidsTrackResult],
    ) -> None:
        self.job.result.advanced = self._count_actions(
            summary.results, {"advance", "next release"}
        )
        self.job.result.skipped = self._count_actions(summary.results, {"skip"})
        self.job.result.new_kids_results = results
        self.job.result.new_kids_prefill = present_entries(
            summary.prefill, self._new_kids_fill_result
        )
        self.job.result.new_kids_postfill = (
            []
            if isinstance(summary, new_kids.Queue2Summary)
            else [self._new_kids_fill_result(result) for result in summary.postfill]
        )
        self.job.result.new_kids_pending_choice = None
        self.job.result.new_kids_resumed = summary.resumed
        self.job.result.new_kids_paused = summary.paused

    def _present_completion_detail(
        self, summary: new_kids.FlushSummary | new_kids.Queue2Summary
    ) -> None:
        if summary.paused:
            self.job.result.detail = f"{self.label} flush paused. Progress was saved."
        elif isinstance(summary, new_kids.Queue2Summary):
            self.job.result.detail = (
                f"{len(summary.results)}"
                " decisions; New Kids "
                f"{summary.new_kids_length_before}"
                " -> "
                f"{summary.new_kids_length_after}"
                "; Queue 2 "
                f"{summary.queue_length_before}"
                " -> "
                f"{summary.queue_length_after}"
                "; "
                f"{len(summary.prefill)}"
                " transfers."
            )
        else:
            transfers = len(summary.prefill) + len(summary.postfill)
            self.job.result.detail = (
                f"{len(summary.results)}"
                " decisions; New Kids "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                "; "
                f"{transfers}"
                " Queue 2 transfers."
            )
        self.append(self.job, self.job.result.detail)

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

    def _count_actions(
        self, results: tuple[new_kids.FlushResult, ...], actions: set[str]
    ) -> int:
        count = 0
        for result in results:
            count += result.action in actions
        return count
