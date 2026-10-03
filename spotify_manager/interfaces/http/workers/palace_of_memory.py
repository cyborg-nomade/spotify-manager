"""Explicit callbacks and wire presentation for PalaceOfMemoryWorker."""

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

from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.palace import PalaceAlbumRefreshResult
from spotify_manager.interfaces.http.models.palace import PalaceAlbumSelectionResult
from spotify_manager.interfaces.http.workers.errors import (
    _PalaceOfMemoryJobCancelledError,
)
from spotify_manager.interfaces.operations import palace_of_memory as palace_of_memory
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class PalaceOfMemoryWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlist_id: Explicit playlist id input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        alphabetical_start: Explicit alphabetical start input or adapter boundary.
        cursor_position: Explicit cursor position input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    playlist_id: str | None
    dry_run: bool
    alphabetical_start: str | None
    cursor_position: int | None
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    cursor_update: palace_of_memory.AlphabeticalCursorUpdate | None = field(init=False)
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one reconnectable Palace fill or cursor adjustment."""
        self._start()
        try:
            summary = self._execute()
        except _PalaceOfMemoryJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except SpotifyException as exc:
            self._spotify_failed(exc)
        except palace_of_memory.PalaceOfMemoryError as exc:
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
        if self.job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        with self.lock:
            self.job.result.detail = message
            self.append(self.job, message)

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _PalaceOfMemoryJobCancelledError

    def retry_call(self, operation: Callable[[], object], description: str) -> object:
        """Apply the original retry policy with job-owned event callbacks.

        Args:
            operation: Original routine-supplied operation.
            description: Original routine-supplied description.

        Returns:
            The original accepted routine callback result.
        """
        if self.job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        result = review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self.echo,
            sleep=self.interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )
        if self.job.cancel_event.is_set():
            raise _PalaceOfMemoryJobCancelledError
        return result

    def _start(self) -> None:
        self.job = self.lookup(self.job_id, command="fill_palace_of_memory")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = (
                "Setting Palace alphabetical cursor"
                if self.cursor_position is not None
                else "Palace of Memory started"
            )
            self.append(self.job, self.job.result.detail)
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)
        self.cursor_update = None

    def _execute(self) -> palace_of_memory.PalaceOfMemorySummary | None:
        summary: palace_of_memory.PalaceOfMemorySummary | None = None
        if self.cursor_position is not None:
            self.cursor_update = palace_of_memory.set_alphabetical_cursor(
                self.spotify,
                self.cursor_position,
                progress_callback=self.echo,
                retry_call=self.retry_call,
            )
        else:
            if self.playlist_id is None:
                raise palace_of_memory.PalaceOfMemoryConfigError(
                    "Palace of Memory playlist is required."
                )
            summary = palace_of_memory.fill_palace_of_memory(
                self.spotify,
                self.playlist_id,
                dry_run=self.dry_run,
                alphabetical_start=self.alphabetical_start,
                echo=self.echo,
                progress_callback=self.echo,
                retry_call=self.retry_call,
            )
        return summary

    def _completed(
        self, summary: palace_of_memory.PalaceOfMemorySummary | None
    ) -> None:
        with self.lock:
            self.job.result.status = "completed"
            if self.cursor_update is not None:
                refresh = self._present_cursor(self.cursor_update)
            elif summary is not None:
                refresh = self._present_fill(summary)
            else:
                raise AssertionError("Palace worker completed without a result")
            self.job.result.palace_album_refresh = PalaceAlbumRefreshResult(
                previous=refresh.previous,
                current=refresh.current,
                added=refresh.added,
                removed=refresh.removed,
                skipped=refresh.skipped,
                persisted=refresh.persisted,
                backup_path=refresh.backup_path,
            )
            self.append(self.job, cast(str, self.job.result.detail))

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Palace of Memory stopped safely. Rerun it to continue."
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

    def _failed(self, exc: palace_of_memory.PalaceOfMemoryError) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"Palace of Memory failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected Palace of Memory error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Palace of Memory error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _palace_album_selection_results(
        self, summary: palace_of_memory.PalaceOfMemorySummary
    ) -> list[PalaceAlbumSelectionResult]:
        entries: list[PalaceAlbumSelectionResult] = []
        for result in summary.results:
            entries.append(
                PalaceAlbumSelectionResult(
                    source=result.source,
                    selected_date=result.selected_date.isoformat()
                    if result.selected_date is not None
                    else None,
                    history_position=result.history_position,
                    albums_on_date=result.albums_on_date,
                    artist=result.artist,
                    album=result.album,
                    spotify_album=result.spotify_album.album
                    if result.spotify_album is not None
                    else None,
                    first_track=result.first_track.name
                    if result.first_track is not None
                    else None,
                    action=result.action,
                )
            )
        return entries

    def _present_cursor(
        self, cursor: palace_of_memory.AlphabeticalCursorUpdate
    ) -> palace_of_memory.SavedAlbumRefresh:
        refresh = cursor.album_refresh
        self.job.result.palace_alphabetical_start_index = cursor.next_index
        self.job.result.palace_alphabetical_next_index = cursor.next_index
        self.job.result.palace_next_album_artist = cursor.next_album.artist
        self.job.result.palace_next_album = cursor.next_album.album
        self.job.result.detail = (
            "Alphabetical cursor set to "
            f"{cursor.next_index + 1}"
            ": "
            f"{cursor.next_album.artist}"
            " - "
            f"{cursor.next_album.album}"
            "."
        )
        return refresh

    def _present_fill(
        self, summary: palace_of_memory.PalaceOfMemorySummary
    ) -> palace_of_memory.SavedAlbumRefresh:
        refresh = summary.album_refresh
        self.job.result.random_org_timestamp = summary.generated_at.isoformat()
        self.job.result.palace_cutoff_date = summary.cutoff_date.isoformat()
        self.job.result.palace_available_dates = summary.available_dates
        self.job.result.palace_alphabetical_start_index = (
            summary.alphabetical_start_index
        )
        self.job.result.palace_alphabetical_next_index = summary.alphabetical_next_index
        self.job.result.palace_alphabetical_cursor_overridden = (
            summary.alphabetical_cursor_overridden
        )
        self.job.result.playlist_length_before = summary.playlist_length_before
        self.job.result.playlist_length_after = summary.playlist_length_after
        self.job.result.added = summary.added
        self.job.result.palace_results = self._palace_album_selection_results(summary)
        verb = "Would add" if self.dry_run else "Added"
        self.job.result.detail = (
            f"{verb} {summary.added} first track(s) to Palace of Memory."
        )
        for result in self.job.result.palace_results:
            self.append(
                self.job,
                (
                    f"{result.source.title()}"
                    ": "
                    f"{result.artist}"
                    " - "
                    f"{result.album}"
                    " -> "
                    f"{result.first_track or 'no match'}"
                    " ("
                    f"{result.action}"
                    ")."
                ),
            )
        return refresh
