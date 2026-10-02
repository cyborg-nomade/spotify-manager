"""Explicit callbacks and wire presentation for BlastWorker."""

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

from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.historical import BlastSelectionResult
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import review_album_limits


@dataclass(kw_only=True)
class BlastWorker:
    """Own one routine job and its explicitly supplied interface dependencies."""

    job_id: str
    spotify: Spotify
    playlist_id: str
    count: int | None
    max_playlist_length: int | None
    dry_run: bool
    connection_failure: str
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _blast_selection_result: Callable[..., BlastSelectionResult]
    _playlist_job_retry: Callable[
        [_BlastJob, Callable[[str], None]], blast_from_past.RetryCall
    ]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one web playlist job and retain progress, logs, and results."""
        self._start()
        try:
            summary = self._execute()
        except blast_from_past.BlastFromPastCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except (blast_from_past.BlastFromPastError, SpotifyException) as exc:
            self._failed(exc)
        except RequestException:
            self._connection_failed()
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

    def _start(self) -> None:
        self.job = self.lookup(self.job_id)
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Playlist routine started"
            self.append(
                self.job,
                ("A blast from the past started")
                + ((" in dry-run mode.") if self.dry_run else (".")),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> blast_from_past.BlastFromPastSpotifySummary:
        summary = blast_from_past.add_blast_from_past_to_spotify(
            self.spotify,
            self.playlist_id,
            count=self.count,
            max_playlist_length=self.max_playlist_length,
            progress_callback=self.echo,
            retry_call=self._playlist_job_retry(self.job, self.echo),
            cancel_check=self.job.cancel_event.is_set,
            dry_run=self.dry_run,
        )
        return summary

    def _completed(self, summary: blast_from_past.BlastFromPastSpotifySummary) -> None:
        selections = [
            self._blast_selection_result(result) for result in summary.results
        ]
        with self.lock:
            self.job.result.status = "completed"
            self.job.result.requested_count = summary.requested_count
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = summary.added
            self.job.result.selections = selections
            if summary.batch is not None:
                self.job.result.random_org_timestamp = (
                    summary.batch.generated_at.isoformat()
                )
            verb = "Would add" if self.dry_run else "Added"
            self.job.result.detail = (
                f"{verb}"
                " "
                f"{summary.added}"
                " of "
                f"{summary.requested_count}"
                " selections; playlist "
                f"{summary.playlist_length_before}"
                " -> "
                f"{summary.playlist_length_after}"
                "."
            )
            for selection in selections:
                target = selection.spotify_match or "no qualifying Spotify match"
                liked_label = " liked" if selection.liked else ""
                self.append(
                    self.job,
                    (
                        f"{selection.selected_date}"
                        ": "
                        f"{selection.lastfm_scrobble}"
                        " -> "
                        f"{target}"
                        " ("
                        f"{selection.action}"
                        f"{liked_label}"
                        ")."
                    ),
                )
            self.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = "A blast from the past was cancelled."
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
            )
            self.append(self.job, self.job.result.detail)

    def _failed(
        self, exc: blast_from_past.BlastFromPastError | SpotifyException
    ) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"Playlist routine failed: {exc}")

    def _connection_failed(self) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.append(self.job, self.job.result.detail)

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected blast-from-the-past error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected playlist error: {exc}"
            self.append(self.job, self.job.result.detail)
