"""Explicit callbacks and wire presentation for SauvignonWorker."""

from collections.abc import Callable
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
from spotify_manager.interfaces import sauvignon_operations as sauvignon
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.recommendations import SauvignonAlbumOption
from spotify_manager.interfaces.http.models.recommendations import (
    SauvignonPendingChoice,
)
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.presenters.recommendations import (
    sauvignon_selection_results,
)
from spotify_manager.interfaces.http.workers.errors import _SauvignonJobCancelledError
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.requests.sauvignon import SauvignonCallbacks
from spotify_manager.interfaces.requests.sauvignon import SauvignonOptions
from spotify_manager.interfaces.requests.sauvignon import SauvignonResources


@dataclass(kw_only=True)
class SauvignonWorker:
    """Execute one reconnectable job with invocation-owned inputs.

    Args:
        credentials: Credentials supplied by the caller.
        options: Options supplied by the caller.
        context: Shared job lock, clock and presentation context.
        job_id: Job id supplied by the caller.
        spotify: Caller-owned Spotify client.
        connection_failure: Connection failure supplied by the caller.
        job: Mutable job record owned by this worker.
        last_progress: Last visible progress observation.
        lastfm: Caller-owned Last.fm client.
        spotify_event_setter: SDK event subscription hook.
        previous_spotify_event_callback: Original SDK event observer restored on exit.
    """

    credentials: LastFmCredentials
    options: SauvignonOptions
    context: PlaylistContext
    job_id: str
    spotify: Spotify
    connection_failure: str
    job: _BlastJob = field(init=False)
    last_progress: str | None = field(init=False, default=None)
    lastfm: LastFmClient = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Run reconnectable Last.fm album discovery for Sauvignon."""
        self._start()
        try:
            summary = self._execute()
        except _SauvignonJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except RequestException:
            self._connection_failed()
        except (
            sauvignon.SauvignonError,
            found_art.FoundArtError,
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

    def progress_callback(self, progress_status: str) -> None:
        """Publish routine progress and observe its cancellation boundary.

        Args:
            progress_status: Original routine-supplied progress status.
        """
        if self.job.cancel_event.is_set():
            raise _SauvignonJobCancelledError
        with self.context.lock:
            self.job.result.detail = progress_status
            if progress_status != self.last_progress:
                self.context.append(self.job, progress_status)
                self.last_progress = progress_status

    def choice_reader(
        self,
        recommendation: sauvignon.AlbumRecommendation,
        options: tuple[sauvignon.SpotifyAlbumOption, ...],
    ) -> str:
        """Present feature options and wait for this job's accepted choice.

        Args:
            recommendation: Original routine-supplied recommendation.
            options: Original routine-supplied options.

        Returns:
            The original accepted routine callback result.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _SauvignonJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.sauvignon_pending_choice = SauvignonPendingChoice(
                artist=recommendation.artist,
                album=recommendation.album,
                score=recommendation.score,
                best_match=recommendation.best_match,
                base_rank=recommendation.base_rank,
                weekly_rank=recommendation.weekly_rank,
                supporting_tracks=list(recommendation.supporting_tracks),
                options=self._sauvignon_album_options(options),
            )
            self.job.result.status = "waiting"
            self.job.result.detail = (
                f"Choose the Spotify edition for {recommendation.artist} - "
                f"{recommendation.album}"
            )
            self.context.append(self.job, self.job.result.detail)
        return await_submission(self.job.choice_event, self._consume_choice_reader)

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _SauvignonJobCancelledError

    def retry_call(self, operation: Callable[[], object], description: str) -> object:
        """Apply the original retry policy with job-owned event callbacks.

        Args:
            operation: Original routine-supplied operation.
            description: Original routine-supplied description.

        Returns:
            The original accepted routine callback result.
        """
        if self.job.cancel_event.is_set():
            raise _SauvignonJobCancelledError
        return review_album_limits.retry_spotify_server_errors(
            operation,
            description,
            echo=self.echo,
            sleep=self.interruptible_sleep,
            retry_delay_seconds=10,
            max_attempts=3,
        )

    def _start(self) -> None:
        self.job = self.context.lookup(
            self.job_id, command="fill_sauvignon_from_lastfm"
        )
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "Sauvignon album discovery started"
            dry_run_suffix = " in dry-run mode" if self.options.dry_run else ""
            self.context.append(
                self.job, f"Sauvignon album discovery started{dry_run_suffix}."
            )
        self.last_progress: str | None = None
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)
        self.lastfm = lastfm_client(
            LastFmCredentials(self.credentials.api_key, self.credentials.username),
            self.echo,
        )

    def _execute(self) -> sauvignon.SauvignonSummary:
        summary = sauvignon.fill_sauvignon_from_lastfm(
            self.spotify,
            self.lastfm,
            self.options,
            SauvignonCallbacks(
                choice_reader=self.choice_reader,
                echo=self.echo,
                progress_callback=self.progress_callback,
                retry_call=self.retry_call,
            ),
            SauvignonResources(),
        )
        return summary

    def _completed(self, summary: sauvignon.SauvignonSummary) -> None:
        results = sauvignon_selection_results(summary.results)
        with self.context.lock:
            self.job.result.status = "paused" if summary.paused else "completed"
            self.job.result.requested_count = summary.requested_count
            self.job.result.week_start = summary.week_start.isoformat()
            self.job.result.history_scrobbles = summary.history_scrobbles
            self.job.result.sauvignon_history_albums = summary.history_albums
            self.job.result.live_scrobbles_added = summary.live_scrobbles_added
            self.job.result.sauvignon_seed_count = summary.seed_count
            self.job.result.sauvignon_track_candidate_count = (
                summary.track_candidate_count
            )
            self.job.result.sauvignon_album_candidate_count = (
                summary.album_candidate_count
            )
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = summary.selected
            self.job.result.dry_run = summary.dry_run
            self.job.result.sauvignon_results = results
            verb = "Would add" if summary.dry_run else "Added"
            self.job.result.detail = (
                f"{verb} {summary.selected} of {summary.requested_count}"
                f" album recommendations; playlist {summary.playlist_length_before}"
                f" -> {summary.playlist_length_after}."
            )
            for result in results:
                target = result.spotify_album or "no selected Spotify edition"
                self.context.append(
                    self.job,
                    f"{result.artist} - {result.album} -> {target} ({result.action}).",
                )
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.context.lock:
            self.job.result.sauvignon_pending_choice = None
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Sauvignon discovery stopped. Cached calls and completed "
                "additions remain saved."
                if not self.options.dry_run
                else "Sauvignon discovery dry run stopped."
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
        exc: sauvignon.SauvignonError
        | found_art.FoundArtError
        | LastFmError
        | SpotifyException,
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"Sauvignon discovery failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected Sauvignon discovery error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected Sauvignon discovery error: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def _consume_choice_reader(self) -> str | None:
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _SauvignonJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.sauvignon_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying Sauvignon album choice"
            self.context.append(self.job, f"Album choice received: {choice}.")
            return choice

    def _sauvignon_album_options(
        self, options: tuple[sauvignon.SpotifyAlbumOption, ...]
    ) -> list[SauvignonAlbumOption]:
        entries: list[SauvignonAlbumOption] = []
        for option in options:
            entries.append(
                SauvignonAlbumOption(
                    spotify_id=option.spotify_id,
                    artist=option.artist,
                    album=option.album,
                    release_type=option.release_type,
                    release_date=option.release_date,
                    total_tracks=option.total_tracks,
                )
            )
        return entries
