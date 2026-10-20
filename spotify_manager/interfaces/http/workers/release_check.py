"""Explicit callbacks and wire presentation for ReleaseCheckWorker."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta
from pathlib import Path

from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.core.state.models import StateError
from spotify_manager.core.state.runtime import get_state_service
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.releases import ReleaseCheckArtistOption
from spotify_manager.interfaces.http.models.releases import ReleaseCheckPendingChoice
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.presenters.releases import (
    release_check_result as _release_check_result,
)
from spotify_manager.interfaces.http.workers.errors import (
    _ReleaseCheckJobCancelledError,
)
from spotify_manager.interfaces.operations import release_check as release_check
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.interfaces.requests.release_check import ReleaseCheckCallbacks
from spotify_manager.interfaces.requests.release_check import ReleaseCheckOptions
from spotify_manager.interfaces.requests.release_check import ReleaseCheckResources


@dataclass(kw_only=True)
class ReleaseCheckWorker:
    """Execute one reconnectable job with invocation-owned inputs.

    Args:
        credentials: Caller-owned credentials.
        options: Caller-owned options.
        context: Caller-owned context.
        job_id: Caller-owned job id.
        spotify: Caller-owned spotify.
        RELEASE_CHECK_STATE_PATH: Caller-owned RELEASE CHECK STATE PATH.
    """

    credentials: LastFmCredentials
    options: ReleaseCheckOptions
    context: PlaylistContext
    job_id: str
    spotify: Spotify
    RELEASE_CHECK_STATE_PATH: Path
    job: _BlastJob = field(init=False)
    lastfm: LastFmClient = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one reconnectable, interactive new-release check."""
        self._start()
        try:
            summary = self._execute()
        except _ReleaseCheckJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except SpotifyException as exc:
            self._spotify_failed(exc)
        except (
            release_check.ReleaseCheckError,
            scrobble_history.ScrobbleHistoryError,
            LastFmError,
            RequestException,
            StateError,
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

    def wait_for_submission(
        self, pending: ReleaseCheckPendingChoice, detail: str
    ) -> str:
        """Publish pending interaction data and consume its submission.

        Args:
            pending: Original routine-supplied pending.
            detail: Original routine-supplied detail.

        Returns:
            The original accepted routine callback result.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _ReleaseCheckJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.release_check_pending_choice = pending
            self.job.result.status = "waiting"
            self.job.result.detail = detail
            self.context.append(self.job, detail)
        return await_submission(
            self.job.choice_event, self._consume_wait_for_submission
        )

    def artist_choice_reader(
        self,
        artist: release_check.RankedArtist,
        candidates: tuple[release_check.SpotifyArtistCandidate, ...],
    ) -> str:
        """Resolve the original ambiguous Spotify artist selection.

        Args:
            artist: Original routine-supplied artist.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        return self.wait_for_submission(
            ReleaseCheckPendingChoice(
                kind="artist",
                artist=artist.name,
                artist_rank=artist.rank,
                artist_scrobbles=artist.scrobbles,
                artist_candidates=self._release_check_artist_options(candidates),
            ),
            f"Choose the Spotify artist for #{artist.rank} {artist.name}.",
        )

    def release_choice_reader(
        self,
        artist: release_check.RankedArtist,
        release: release_check.ReleaseCandidate,
        track: release_check.ReleaseTrack,
        destinations: tuple[str, ...],
        unattached_single: bool,
    ) -> str:
        """Read the destination decision for the proposed release.

        Args:
            artist: Original routine-supplied artist.
            release: Original routine-supplied release.
            track: Original routine-supplied track.
            destinations: Original routine-supplied destinations.
            unattached_single: Original routine-supplied unattached single.

        Returns:
            The original accepted routine callback result.
        """
        return self.wait_for_submission(
            ReleaseCheckPendingChoice(
                kind="release",
                artist=artist.name,
                artist_rank=artist.rank,
                artist_scrobbles=artist.scrobbles,
                release=release.name,
                release_type=release.release_type,
                release_date=release.release_date,
                first_track=track.name,
                destinations=list(destinations),
                tags=list(release_check.release_tags(release)),
                unattached_single=unattached_single,
            ),
            (
                f"Review {release.release_type.casefold()} {release.name} by "
                f"{artist.name}."
            ),
        )

    def update_progress(self, completed: int, total: int, detail: str) -> None:
        """Publish original release-check counters and display detail.

        Args:
            completed: Original routine-supplied completed.
            total: Original routine-supplied total.
            detail: Original routine-supplied detail.
        """
        with self.context.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = detail
            self.context.append(self.job, detail)

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _ReleaseCheckJobCancelledError

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
        self.job = self.context.lookup(self.job_id, command="check_new_releases")
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = "New-release check started"
            self.context.append(
                self.job,
                (
                    f"New-release check started"
                    f"{(' in dry-run mode' if self.options.dry_run else '')}."
                ),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)
        self.lastfm = lastfm_client(
            LastFmCredentials(self.credentials.api_key, self.credentials.username),
            self.echo,
        )

    def _execute(self) -> release_check.ReleaseCheckSummary:
        summary = release_check.run_release_check(
            self.spotify,
            self.lastfm,
            ReleaseCheckOptions(
                playlists=self.options.playlists,
                expected_username=self.credentials.username,
                dry_run=self.options.dry_run,
            ),
            ReleaseCheckCallbacks(
                artist_choice_reader=self.artist_choice_reader,
                release_choice_reader=self.release_choice_reader,
                progress_callback=self.update_progress,
                retry_call=self.retry_call,
            ),
            ReleaseCheckResources(
                state_path=self.RELEASE_CHECK_STATE_PATH,
                state_service=get_state_service(),
            ),
        )
        return summary

    def _completed(self, summary: release_check.ReleaseCheckSummary) -> None:
        results = [_release_check_result(result) for result in summary.results]
        with self.context.lock:
            self.job.result.status = "paused" if summary.paused else "completed"
            self.job.result.run_id = summary.run_id
            self.job.result.processed = summary.artists_processed
            self.job.result.total = summary.artists_total
            self.job.result.release_check_checked_from = (
                summary.checked_from.isoformat()
            )
            self.job.result.release_check_checked_through = (
                summary.checked_through.isoformat()
            )
            self.job.result.release_check_resumed = summary.resumed
            self.job.result.release_check_paused = summary.paused
            self.job.result.release_check_wine_cellar_duplicates_removed = (
                summary.wine_cellar_duplicates_removed
            )
            self.job.result.release_check_wine_cellar_added = summary.wine_cellar_added
            self.job.result.release_check_new_vintage_added = summary.new_vintage_added
            self.job.result.release_check_results = results
            if summary.history_refresh is not None:
                self.job.result.live_scrobbles_added = (
                    summary.history_refresh.live_scrobbles_added
                )
                self.job.result.history_scrobbles = (
                    summary.history_refresh.total_scrobbles
                )
            if summary.paused:
                self.job.result.detail = (
                    "New-release check paused. Rerun it to resume "
                    "from the durable checkpoint."
                )
            else:
                verb = "Would add" if self.options.dry_run else "Added"
                cleanup = "would normalize" if self.options.dry_run else "normalized"
                self.job.result.detail = (
                    f"{summary.artists_processed}/{summary.artists_total}"
                    f" artists checked. {verb} {summary.wine_cellar_added}"
                    f" to Wine Cellar and {summary.new_vintage_added}"
                    f" to New Vintage; {summary.wine_cellar_duplicates_removed}"
                    f" duplicate Wine Cellar track(s) {cleanup}."
                )
            self.context.append(self.job, self.job.result.detail)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.context.lock:
            self.job.result.release_check_pending_choice = None
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "New-release check stopped. Durable progress was preserved."
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
                review_album_limits.format_transient_spotify_failure(exc) + "."
            )
            self.context.append(self.job, self.job.result.detail)

    def _spotify_failed(self, exc: SpotifyException) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Spotify request failed: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def _failed(
        self,
        exc: release_check.ReleaseCheckError
        | scrobble_history.ScrobbleHistoryError
        | LastFmError
        | RequestException
        | StateError,
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"New-release check failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected new-release check error")
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected new-release check error: {exc}"
            self.context.append(self.job, self.job.result.detail)

    def _consume_wait_for_submission(self) -> str | None:
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _ReleaseCheckJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.release_check_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying release-check choice"
            if choice.startswith(release_check.CHOICE_SEARCH_PREFIX):
                logged_choice = "custom artist search"
            else:
                logged_choice = choice
            self.context.append(
                self.job, f"Release-check choice received: {logged_choice}."
            )
            return choice

    def _release_check_artist_options(
        self, candidates: tuple[release_check.SpotifyArtistCandidate, ...]
    ) -> list[ReleaseCheckArtistOption]:
        entries: list[ReleaseCheckArtistOption] = []
        for candidate in candidates:
            entries.append(
                ReleaseCheckArtistOption(
                    spotify_id=candidate.spotify_id,
                    name=candidate.name,
                    popularity=candidate.popularity,
                    followers=candidate.followers,
                    exact_name=candidate.exact_name,
                )
            )
        return entries
