"""Explicit callbacks and wire presentation for NewKidsWorker."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import timedelta
from typing import Literal

from requests.exceptions import RequestException
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.application.ports.spotify_client import SpotifyClient as Spotify
from spotify_manager.bootstrap.clients import LastFmCredentials
from spotify_manager.bootstrap.clients import lastfm_client
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.infrastructure.lastfm_async import (
    AsyncLastFmClient as LastFmClient,
)
from spotify_manager.infrastructure.spotify.events import SpotifyEvents
from spotify_manager.infrastructure.spotify.retry import SpotifyRetries
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discovery import NewKidsPendingChoice
from spotify_manager.interfaces.http.models.discovery import NewKidsReleaseOption
from spotify_manager.interfaces.http.models.discovery import NewKidsTrackResult
from spotify_manager.interfaces.http.playlist_context import PlaylistContext
from spotify_manager.interfaces.http.playlist_retry import RateLimitRetries
from spotify_manager.interfaces.http.presenters.discovery import (
    new_kids_fill_result as _new_kids_fill_result,
)
from spotify_manager.interfaces.http.presenters.discovery import new_kids_fill_results
from spotify_manager.interfaces.http.presenters.discovery import (
    new_kids_track_result as _new_kids_track_result,
)
from spotify_manager.interfaces.http.workers.errors import _NewKidsJobCancelledError
from spotify_manager.interfaces.operations import found_art as found_art
from spotify_manager.interfaces.operations import new_kids as new_kids
from spotify_manager.interfaces.operations import (
    review_album_limits as review_album_limits,
)
from spotify_manager.interfaces.operations import scrobble_history as scrobble_history
from spotify_manager.interfaces.requests.discovery import DiscoveryOptions
from spotify_manager.interfaces.requests.discovery import DiscoveryResources
from spotify_manager.routines import composer_playlists


@dataclass(kw_only=True)
class NewKidsWorker:
    """Execute one reconnectable job with invocation-owned inputs.

    Args:
        options: Options supplied by the caller.
        context: Shared job lock, clock and presentation context.
        job_id: Job id supplied by the caller.
        spotify: Caller-owned Spotify client.
        command: Command supplied by the caller.
        rate_limit_delay: Rate limit delay supplied by the caller.
        connection_failure: Connection failure supplied by the caller.
        job: Mutable job record owned by this worker.
        label: Visible command label.
        lastfm: Caller-owned Last.fm client.

    Attributes:
        events: SDK event subscription retaining the original setter binding.
    """

    options: DiscoveryOptions
    context: PlaylistContext
    job_id: str
    spotify: Spotify
    command: Literal["flush_new_kids", "flush_queue_2"]
    rate_limit_delay: int
    connection_failure: str
    job: _BlastJob = field(init=False)
    label: str = field(init=False)
    lastfm: LastFmClient = field(init=False)
    events: SpotifyEvents = field(init=False)

    async def run(self) -> None:
        """Execute one interactive album-discovery flush as a reconnectable job."""
        self._start()
        try:
            summary = await self._execute()
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
            raise _NewKidsJobCancelledError
        with self.context.lock:
            self.job.result.processed = completed
            self.job.result.total = total
            self.job.result.detail = progress_status

    async def choose(
        self, artist: str, candidates: tuple[new_kids.ChoiceCandidate, ...]
    ) -> str:
        """Present feature options and wait for this job's accepted choice.

        Args:
            artist: Original routine-supplied artist.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        with self.context.lock:
            if self.job.cancel_event.is_set():
                raise _NewKidsJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.new_kids_pending_choice = NewKidsPendingChoice(
                artist=artist, releases=self._new_kids_release_options(candidates)
            )
            self.job.result.status = "waiting"
            self.job.result.detail = f"Choose the next release for {artist}"
            self.context.append(self.job, self.job.result.detail)
        return await await_submission(self.job.choice_event, self)

    async def sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if await self.job.cancel_event.wait(seconds):
            raise _NewKidsJobCancelledError

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Open the original retry boundary for a directly executed operation.

        Args:
            description: Original request description.

        Returns:
            Attempt scopes retaining the original delay, limit and cancellation rules.
        """
        return RateLimitRetries(SpotifyRetries(self, self, 10, 3), self).attempts(
            description
        )

    def _start(self) -> None:
        self.label = "Queue 2" if self.command == "flush_queue_2" else "New Kids"
        self.job = self.context.lookup(self.job_id, command=self.command)
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.context.clock.now(UTC).isoformat()
            self.job.result.detail = f"{self.label} flush started"
            self.context.append(
                self.job,
                (
                    f"{self.label} flush started"
                    f"{(' in dry-run mode' if self.options.dry_run else '')}."
                ),
            )
        self.events = SpotifyEvents(self.spotify)
        self.events.subscribe(self)

    async def _execute(self) -> new_kids.FlushSummary | new_kids.Queue2Summary:
        configuration = self.context.settings.load()
        lastfm_api_key, lastfm_username = found_art.validate_lastfm_configuration(
            configuration.lastfm_api_key, configuration.lastfm_username
        )
        self.lastfm = lastfm_client(
            LastFmCredentials(lastfm_api_key, lastfm_username), self
        )
        options = self.options
        interaction = self
        if self.command == "flush_queue_2":
            resources = DiscoveryResources(
                log_path=new_kids.DEFAULT_QUEUE_2_LOG_PATH,
                lastfm=self.lastfm,
                lastfm_username=lastfm_username,
            )
            return await new_kids.flush_queue_2(
                self.spotify, options, interaction, resources
            )
        resources = DiscoveryResources(
            lastfm=self.lastfm, lastfm_username=lastfm_username
        )
        return await new_kids.flush_new_kids(
            self.spotify, options, interaction, resources
        )

    def _completed(
        self, summary: new_kids.FlushSummary | new_kids.Queue2Summary
    ) -> None:
        results = [_new_kids_track_result(result) for result in summary.results]
        with self.context.lock:
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
        self.events.restore()
        with self.context.lock:
            self.job.result.new_kids_pending_choice = None
            self.job.result.completed_at = self.context.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.context.lock:
            self.job.result.status = "cancelled"
            self.job.result.new_kids_pending_choice = None
            self.job.result.retry_at = None
            self.job.result.detail = (
                f"{self.label} flush stopped. Progress was saved."
                if not self.options.dry_run
                else f"{self.label} dry run stopped."
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
            self.job.result.new_kids_pending_choice = None
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
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = (
                review_album_limits.format_transient_spotify_failure(exc)
                + ". Progress was saved."
            )
            self.context.append(self.job, self.job.result.detail)

    def _connection_failed(self) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = self.connection_failure
            self.context.append(self.job, self.job.result.detail)

    def _failed(
        self,
        exc: new_kids.NewKidsError
        | found_art.FoundArtConfigError
        | scrobble_history.ScrobbleHistoryError
        | LastFmError
        | SpotifyException,
    ) -> None:
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = str(exc)
            self.context.append(self.job, f"{self.label} flush failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.context.logger.exception("Unexpected %s flush error", self.label)
        with self.context.lock:
            self.job.result.status = "failed"
            self.job.result.new_kids_pending_choice = None
            self.job.result.detail = f"Unexpected {self.label} error: {exc}"
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
                raise _NewKidsJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.new_kids_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying release choice"
            self.context.append(self.job, f"Release choice received: {choice}.")
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
        self.job.result.new_kids_prefill = new_kids_fill_results(summary.prefill)
        self.job.result.new_kids_postfill = (
            []
            if isinstance(summary, new_kids.Queue2Summary)
            else [_new_kids_fill_result(result) for result in summary.postfill]
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
                f"{len(summary.results)} decisions; New Kids "
                f"{summary.new_kids_length_before} -> "
                f"{summary.new_kids_length_after}; Queue 2 "
                f"{summary.queue_length_before} -> {summary.queue_length_after}; "
                f"{len(summary.prefill)} transfers."
            )
        else:
            transfers = len(summary.prefill) + len(summary.postfill)
            self.job.result.detail = (
                f"{len(summary.results)} decisions; New Kids "
                f"{summary.playlist_length_before} -> "
                f"{summary.playlist_length_after}; {transfers} Queue 2 transfers."
            )
        self.context.append(self.job, self.job.result.detail)

    async def wait_for_rate_limit(
        self, exc: review_album_limits.SpotifyRateLimitError, description: str
    ) -> None:
        """Wait at the job's original rate-limit boundary.

        Args:
            exc: Original operation context.
            description: Original operation context.
        """
        delay = max(1, exc.retry_after_seconds or self.rate_limit_delay)
        retry_at = self.context.clock.now(UTC) + timedelta(seconds=delay)
        message = (
            f"Spotify rate limit reached while {description}"
            f". Retrying automatically "
            f"{review_album_limits.format_retry_delay(delay)}."
        )
        with self.context.lock:
            self.job.result.status = "running"
            self.job.result.retry_at = retry_at.isoformat()
            self.job.result.detail = message
            self.context.append(self.job, message)
        await self.sleep(delay)
        with self.context.lock:
            self.job.result.retry_at = None
            self.job.result.detail = f"Retrying {description}."
            self.context.append(self.job, self.job.result.detail)

    def _count_actions(
        self, results: tuple[new_kids.FlushResult, ...], actions: set[str]
    ) -> int:
        count = 0
        for result in results:
            count += result.action in actions
        return count

    def retry_accepted(self) -> None:
        """Clear the original retry timestamp after a successful operation."""
        with self.context.lock:
            self.job.result.retry_at = None
