"""Explicit callbacks and wire presentation for DiscographyWorker."""

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
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.discography import DiscographyArtistResult
from spotify_manager.interfaces.http.models.discography import DiscographyPendingChoice
from spotify_manager.interfaces.http.models.discography import DiscographyReleaseOption
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldArtistOption,
)
from spotify_manager.interfaces.http.presenters.collections import present_entries
from spotify_manager.interfaces.http.workers.errors import _DiscographyJobCancelledError
from spotify_manager.routines import discography
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import something_old


@dataclass(kw_only=True)
class DiscographyWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlist_ids: Explicit playlist ids input or adapter boundary.
        queue_3_playlist_id: Explicit queue 3 playlist id input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _discography_artist_result: Explicit discography artist result input or adapter
            boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    playlist_ids: dict[discography.QueueName, str]
    queue_3_playlist_id: str
    dry_run: bool
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _discography_artist_result: Callable[..., DiscographyArtistResult]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute one reload-safe interactive discography planning job."""
        self._start()
        try:
            self._execute()
        except _DiscographyJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except SpotifyException as exc:
            self._spotify_failed(exc)
        except (discography.DiscographyError, RequestException) as exc:
            self._failed(exc)
        except Exception as exc:
            self._unexpected_failure(exc)
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

    def wait_for_submission(
        self, pending: DiscographyPendingChoice, detail: str
    ) -> tuple[str, tuple[str, ...]]:
        """Publish pending interaction data and consume its submission.

        Args:
            pending: Original routine-supplied pending.
            detail: Original routine-supplied detail.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _DiscographyJobCancelledError
            self.job.submitted_choice = None
            self.job.submitted_order = None
            self.job.choice_event.clear()
            self.job.result.discography_pending_choice = pending
            self.job.result.status = "waiting"
            self.job.result.detail = detail
            self.append(self.job, detail)
        return await_submission(
            self.job.choice_event, self._consume_wait_for_submission
        )

    def release_selector(
        self,
        artist: discography.QueueArtist,
        releases: tuple[discography.CatalogRelease, ...],
    ) -> tuple[str, ...]:
        """Read the original discography release selection.

        Args:
            artist: Original routine-supplied artist.
            releases: Original routine-supplied releases.

        Returns:
            The original accepted routine callback result.
        """
        choice, release_ids = self.wait_for_submission(
            DiscographyPendingChoice(
                kind="releases",
                artist=artist.name,
                queue=discography.QUEUE_LABELS[artist.queue],
                releases=self._discography_release_options(releases),
                default_release_ids=self._default_release_ids(releases),
            ),
            (f"Choose the releases to count for {artist.name}."),
        )
        if choice == "quit":
            raise _DiscographyJobCancelledError
        if choice == "none":
            return ()
        return release_ids

    def historical_artist_choice_reader(
        self,
        artist_name: str,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        """Resolve a historical artist using the original choices.

        Args:
            artist_name: Original routine-supplied artist name.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        choice, _release_ids = self.wait_for_submission(
            DiscographyPendingChoice(
                kind="artist",
                artist=artist_name,
                queue=discography.QUEUE_LABELS["memory_lane"],
                artist_candidates=self._something_old_artist_options(candidates),
            ),
            (f"Choose the exact Spotify artist for {artist_name}."),
        )
        return choice

    def progress(self, detail: str) -> None:
        """Publish original discography progress text.

        Args:
            detail: Original routine-supplied detail.
        """
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _DiscographyJobCancelledError
            self.job.result.detail = detail
            self.append(self.job, detail)

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _DiscographyJobCancelledError

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
        self.job = self.lookup(self.job_id, command="plan_discographies")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Discography planning started"
            self.append(
                self.job,
                (
                    "Discography planning started"
                    f"{(' in dry-run mode' if self.dry_run else '')}"
                    "."
                ),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)

    def _execute(self) -> None:
        plan = discography.build_discography_plan(
            self.spotify,
            self.playlist_ids,
            self.release_selector,
            queue_3_playlist_id=self.queue_3_playlist_id,
            historical_artist_choice_reader=self.historical_artist_choice_reader,
            retry_call=self.retry_call,
            progress_callback=self.progress,
        )
        self._present_plan(plan)
        self._complete_or_apply_plan(plan)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.discography_pending_choice = None
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.detail = (
                "Discography planning stopped; nothing else changed."
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
            self.job.result.status = "failed"
            self.job.result.detail = f"Spotify request failed: {exc}"
            self.append(self.job, self.job.result.detail)

    def _failed(self, exc: discography.DiscographyError | RequestException) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = str(exc)
            self.append(self.job, f"Discography planning failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected discography planning error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.detail = f"Unexpected discography planning error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _consume_wait_for_submission(self) -> tuple[str, tuple[str, ...]] | None:
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _DiscographyJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            release_ids = self.job.submitted_order or ()
            self.job.submitted_choice = None
            self.job.submitted_order = None
            self.job.choice_event.clear()
            self.job.result.discography_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying discography choice"
            self.append(self.job, f"Discography choice received: {choice}.")
            return (choice, release_ids)

    def _discography_release_options(
        self, releases: tuple[discography.CatalogRelease, ...]
    ) -> list[DiscographyReleaseOption]:
        entries: list[DiscographyReleaseOption] = []
        for release in releases:
            entries.append(
                DiscographyReleaseOption(
                    spotify_id=release.spotify_id,
                    name=release.name,
                    release_type=release.release_type,
                    release_date=release.chronology_date,
                    total_tracks=release.total_tracks,
                    saved=release.saved,
                    default=release.default,
                )
            )
        return entries

    def _something_old_artist_options(
        self, candidates: tuple[something_old.SpotifyArtistCandidate, ...]
    ) -> list[SomethingOldArtistOption]:
        entries: list[SomethingOldArtistOption] = []
        for candidate in candidates:
            entries.append(
                SomethingOldArtistOption(
                    spotify_id=candidate.spotify_id,
                    name=candidate.name,
                    popularity=candidate.popularity,
                    followers=candidate.followers,
                )
            )
        return entries

    def _present_plan(self, plan: discography.DiscographyPlan) -> None:
        with self.lock:
            self.job.result.discography_start_queue = discography.QUEUE_LABELS[
                plan.start_queue
            ]
            self.job.result.discography_next_queue = discography.QUEUE_LABELS[
                plan.next_queue
            ]
            self.job.result.discography_total_releases = plan.total_releases
            self.job.result.discography_days = plan.days
            self.job.result.discography_open_slots = plan.open_slots
            self.job.result.discography_results = present_entries(
                plan.artists, self._discography_artist_result
            )

    def _complete_or_apply_plan(self, plan: discography.DiscographyPlan) -> None:
        if not plan.artists:
            with self.lock:
                self.job.result.status = "completed"
                self.job.result.detail = "No artists with selected releases were found."
                self.append(self.job, self.job.result.detail)
            return
        if self.dry_run:
            with self.lock:
                self.job.result.status = "completed"
                self.job.result.detail = (
                    "Dry run complete: "
                    f"{plan.total_releases}"
                    " releases over "
                    f"{plan.days:g}"
                    " days. Playlists and state were unchanged."
                )
                self.append(self.job, self.job.result.detail)
            return
        choice, _release_ids = self.wait_for_submission(
            DiscographyPendingChoice(kind="confirm"),
            "Confirm removal from the source queues and Queue 3 where applicable.",
        )
        if choice == "quit":
            raise _DiscographyJobCancelledError
        if choice == "keep":
            with self.lock:
                self.job.result.status = "completed"
                self.job.result.detail = (
                    "Discography plan complete; playlist markers and "
                    "state were kept unchanged."
                )
                self.append(self.job, self.job.result.detail)
            return
        self._apply_plan(plan)

    def _apply_plan(self, plan: discography.DiscographyPlan) -> None:
        summary = discography.apply_discography_plan(
            self.spotify,
            plan,
            retry_call=self.retry_call,
            progress_callback=self.progress,
        )
        with self.lock:
            self.job.result.status = "completed"
            self.job.result.discography_removed_artists = summary.removed_artists
            self.job.result.discography_removed_markers = summary.removed_markers
            self.job.result.detail = (
                "Removed "
                f"{summary.removed_artists}"
                " artists and "
                f"{summary.removed_markers}"
                " marker tracks. The next run starts with "
                f"{discography.QUEUE_LABELS[summary.next_queue]}"
                "."
            )
            self.append(self.job, self.job.result.detail)

    def _default_release_ids(
        self, releases: tuple[discography.CatalogRelease, ...]
    ) -> list[str]:
        identifiers = []
        for release in releases:
            if release.default:
                identifiers.append(release.spotify_id)
        return identifiers
