"""Explicit callbacks and wire presentation for BlastArtistWorker."""

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
from spotify_manager.interfaces.http.models.historical import DormantArtistResultEntry
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.playlist_retry import PlaylistRetry
from spotify_manager.interfaces.operations import blast_from_past as blast_from_past
from spotify_manager.interfaces.operations import (
    blast_from_past_artists as blast_from_past_artists,
)
from spotify_manager.interfaces.operations import new_kids as new_kids
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)


@dataclass(kw_only=True)
class BlastArtistWorker:
    """Execute one reconnectable job and present its accepted outcome.

    Args:
        context: Invocation-owned context.
        job_id: Invocation-owned job id.
        spotify: Invocation-owned spotify.
        playlist_id: Invocation-owned playlist id.
        count: Invocation-owned count.
        dry_run: Invocation-owned dry run.
        connection_failure: Invocation-owned connection failure.
    """

    context: PlaylistContext
    job_id: str
    spotify: Spotify
    playlist_id: str
    count: int
    dry_run: bool
    connection_failure: str
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one alphabetic dormant-artist playlist update."""
        self._start()
        try:
            summary = self._execute()
        except blast_from_past.BlastFromPastCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except (
            blast_from_past.BlastFromPastError,
            new_kids.NewKidsError,
            SpotifyException,
        ) as exc:
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

    def _echo_progress(self, completed: int, total: int, message: str) -> None:
        self.echo(message)

    def _start(self) -> None:
        self.job = self.context.lookup(
            self.job_id, command="blast_from_the_past_artists"
        )
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Reading recently dormant Last.fm artists"
            self.context.append(
                self.job,
                "Dormant-artist recovery started"
                + (" in dry-run mode." if self.dry_run else "."),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> blast_from_past_artists.DormantArtistSummary:
        summary = blast_from_past_artists.add_dormant_artists_to_blast_from_past(
            self.spotify,
            self.playlist_id,
            count=self.count,
            echo=self.echo,
            progress_callback=self._echo_progress,
            retry_call=PlaylistRetry(self.job, self.echo).call,
            cancel_check=self.job.cancel_event.is_set,
            dry_run=self.dry_run,
        )
        return summary

    def _completed(self, summary: blast_from_past_artists.DormantArtistSummary) -> None:
        results = self._dormant_artist_result_entrys(summary)
        with self.context.lock:
            self.job.result.status = "completed"
            self.job.result.requested_count = summary.requested_count
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = summary.added
            self.job.result.candidate_count = summary.candidate_count
            self.job.result.dormant_artist_years = list(summary.history_years)
            self.job.result.dormant_artist_current_year = summary.current_year
            self.job.result.dormant_artist_represented = summary.represented_count
            self.job.result.dormant_artist_results = results
            verb = "Would add" if self.dry_run else "Added"
            self.job.result.detail = (
                f"{verb} {summary.added} of {summary.requested_count}"
                f" dormant artists; playlist {summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}."
            )
            for result in results:
                target = (
                    f"{result.spotify_artist} - {result.track}"
                    if result.track
                    else result.action
                )
                self.context.append(
                    self.job,
                    f"{result.artist} ({result.scrobbles} scrobbles) -> {target}.",
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
            self.job.result.detail = "Dormant-artist recovery was cancelled."
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
        self,
        exc: blast_from_past.BlastFromPastError
        | new_kids.NewKidsError
        | SpotifyException,
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Dormant-artist recovery failed: {exc}")

    def _connection_failed(self) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = self.connection_failure
            self.context.append(self.job, self.job.result.detail)

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected dormant-artist recovery error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected dormant-artist error: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def _dormant_artist_result_entrys(
        self, summary: blast_from_past_artists.DormantArtistSummary
    ) -> list[DormantArtistResultEntry]:
        entries: list[DormantArtistResultEntry] = []
        for result in summary.results:
            entries.append(
                DormantArtistResultEntry(
                    artist=result.artist,
                    scrobbles=result.scrobbles,
                    spotify_artist=result.spotify_artist,
                    track=result.track,
                    popularity=result.popularity,
                    action=result.action,
                )
            )
        return entries
