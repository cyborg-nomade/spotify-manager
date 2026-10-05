"""Explicit callbacks and wire presentation for DailyMindRadioWorker."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.playlist_retry import PlaylistRetry
from spotify_manager.interfaces.http.presenters.collections import date_strings
from spotify_manager.interfaces.http.presenters.collections import present_entries
from spotify_manager.interfaces.http.presenters.historical import (
    blast_selection_result as _blast_selection_result,
)
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import daily_mind_radio as daily_mind_radio
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class DailyMindRadioWorker:
    """Execute one reconnectable job and present its accepted outcome.

    Args:
        context: Invocation-owned context.
        job_id: Invocation-owned job id.
        spotify: Invocation-owned spotify.
        playlist_id: Invocation-owned playlist id.
        dry_run: Invocation-owned dry run.
        connection_failure: Invocation-owned connection failure.
    """

    context: PlaylistContext
    job_id: str
    spotify: Spotify
    playlist_id: str
    dry_run: bool
    connection_failure: str
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one Daily Mind Radio web job and retain its complete trace."""
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
        with self.context.lock:
            self.job.result.detail = message
            self.context.append(self.job, message)

    def _start(self) -> None:
        self.job = self.context.lookup(self.job_id, command="daily_mind_radio")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Playlist routine started"
            self.context.append(
                self.job,
                "Daily Mind Radio started"
                + (" in dry-run mode." if self.dry_run else "."),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> daily_mind_radio.DailyMindRadioSpotifySummary:
        summary = daily_mind_radio.add_daily_mind_radio_to_spotify(
            self.spotify,
            self.playlist_id,
            progress_callback=self.echo,
            retry_call=PlaylistRetry(self.job, self.echo).call,
            cancel_check=self.job.cancel_event.is_set,
            dry_run=self.dry_run,
        )
        return summary

    def _completed(
        self, summary: daily_mind_radio.DailyMindRadioSpotifySummary
    ) -> None:
        selections = present_entries(summary.results, _blast_selection_result)
        with self.context.lock:
            self.job.result.status = "completed"
            self.job.result.requested_count = len(summary.batch.selections)
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = summary.added
            self.job.result.target_dates = date_strings(summary.batch.target_dates)
            self.job.result.missing_dates = date_strings(summary.batch.missing_dates)
            self.job.result.selections = selections
            if summary.batch.generated_at is not None:
                self.job.result.random_org_timestamp = (
                    summary.batch.generated_at.isoformat()
                )
            if summary.playlist_length_before is None:
                self.job.result.detail = (
                    "No anniversary dates had scrobbles; nothing was added."
                )
            else:
                verb = "Would add" if self.dry_run else "Added"
                self.job.result.detail = (
                    f"{verb} {summary.added} of {len(summary.batch.selections)}"
                    f" populated dates; playlist {summary.playlist_length_before}"
                    f" -> {summary.playlist_length_after}."
                )
            for selection in selections:
                target = selection.spotify_match or "no qualifying Spotify match"
                liked_label = " liked" if selection.liked else ""
                self.context.append(
                    self.job,
                    (
                        f"{selection.selected_date}: {selection.lastfm_scrobble}"
                        f" -> {target} ({selection.action}{liked_label})."
                    ),
                )
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.context.lock:
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = "Daily Mind Radio was cancelled."
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
            )
            self.context.append(self.job, self.job.result.detail)

    def _failed(
        self, exc: blast_from_past.BlastFromPastError | SpotifyException
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Playlist routine failed: {exc}")

    def _connection_failed(self) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.context.append(self.job, self.job.result.detail)

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected Daily Mind Radio error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected playlist error: {exc}"
            self.context.append(self.job, self.job.result.detail)
