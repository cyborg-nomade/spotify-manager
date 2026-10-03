"""Explicit callbacks and wire presentation for SomethingOldWorker."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from threading import Lock

from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.client.lastfm import LastFmClient
from spotify_manager.client.lastfm import LastFmError
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import EventSetter
from spotify_manager.interfaces.http.job_records import PlaylistJob as _BlastJob
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldArtistOption,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldPendingChoice,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldRankingEntry,
)
from spotify_manager.interfaces.http.models.something_old import (
    SomethingOldReleaseOption,
)
from spotify_manager.interfaces.http.models.something_old import SomethingOldTrackResult
from spotify_manager.interfaces.http.workers.errors import (
    _SomethingOldJobCancelledError,
)
from spotify_manager.routines import review_album_limits
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import slow_listening
from spotify_manager.routines import something_old


@dataclass(kw_only=True)
class SomethingOldWorker:
    """Own one routine job and its explicitly supplied interface dependencies.

    Args:
        job_id: Explicit job id input or adapter boundary.
        spotify: Explicit spotify input or adapter boundary.
        playlist_id: Explicit playlist id input or adapter boundary.
        api_key: Explicit api key input or adapter boundary.
        username: Explicit username input or adapter boundary.
        dry_run: Explicit dry run input or adapter boundary.
        create_lastfm: Explicit create lastfm input or adapter boundary.
        logger: Explicit logger input or adapter boundary.
        append: Explicit append input or adapter boundary.
        lock: Explicit lock input or adapter boundary.
        _something_old_date: Explicit something old date input or adapter boundary.
        _something_old_track_result: Explicit something old track result input or
            adapter boundary.
        clock: Explicit clock input or adapter boundary.
        lookup: Explicit lookup input or adapter boundary.
    """

    job_id: str
    spotify: Spotify
    playlist_id: str
    api_key: str
    username: str
    dry_run: bool
    create_lastfm: Callable[..., LastFmClient]
    logger: logging.Logger
    append: Callable[[_BlastJob, str], None]
    lock: Lock
    _something_old_date: Callable[[int], str]
    _something_old_track_result: Callable[..., SomethingOldTrackResult]
    clock: type[datetime]
    lookup: Callable[..., _BlastJob]
    job: _BlastJob = field(init=False)
    lastfm: LastFmClient = field(init=False)
    spotify_event_setter: EventSetter | None = field(init=False)
    previous_spotify_event_callback: EventCallback | None = field(init=False)

    def run(self) -> None:
        """Execute Something Old as a reconnectable interactive web job."""
        self._start()
        try:
            summary = self._execute()
        except _SomethingOldJobCancelledError:
            self._cancelled()
        except review_album_limits.SpotifyRateLimitError as exc:
            self._rate_limited(exc)
        except review_album_limits.SpotifyTransientServerError as exc:
            self._temporarily_unavailable(exc)
        except SpotifyException as exc:
            self._spotify_failed(exc)
        except (
            something_old.SomethingOldError,
            scrobble_history.ScrobbleHistoryError,
            LastFmError,
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

    def wait_for_submission(
        self, pending: SomethingOldPendingChoice, detail: str
    ) -> str:
        """Publish pending interaction data and consume its submission.

        Args:
            pending: Original routine-supplied pending.
            detail: Original routine-supplied detail.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _SomethingOldJobCancelledError
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.something_old_pending_choice = pending
            self.job.result.status = "waiting"
            self.job.result.detail = detail
            self.append(self.job, detail)
        return await_submission(
            self.job.choice_event, self._consume_wait_for_submission
        )

    def artist_choice_reader(
        self,
        artist: something_old.GoldenOldieArtist,
        candidates: tuple[something_old.SpotifyArtistCandidate, ...],
    ) -> str:
        """Resolve the original ambiguous Spotify artist selection.

        Args:
            artist: Original routine-supplied artist.
            candidates: Original routine-supplied candidates.

        Returns:
            The original accepted routine callback result.
        """
        average_date = self._something_old_date(artist.average_scrobble_ms)
        with self.lock:
            self.job.result.something_old_artist = artist.artist
            self.job.result.something_old_average_scrobble_date = average_date
        return self.wait_for_submission(
            SomethingOldPendingChoice(
                kind="artist",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=average_date,
                artist_candidates=self._something_old_artist_options(candidates),
            ),
            (f"Choose the exact Spotify artist for {artist.artist}."),
        )

    def mode_reader(
        self,
        artist: something_old.GoldenOldieArtist,
        spotify_artist: something_old.SpotifyArtistCandidate,
    ) -> str:
        """Read the original Something Old selection mode.

        Args:
            artist: Original routine-supplied artist.
            spotify_artist: Original routine-supplied spotify artist.

        Returns:
            The original accepted routine callback result.
        """
        with self.lock:
            self.job.result.something_old_artist = artist.artist
            self.job.result.something_old_average_scrobble_date = (
                self._something_old_date(artist.average_scrobble_ms)
            )
            self.job.result.something_old_spotify_artist = spotify_artist.name
        return self.wait_for_submission(
            SomethingOldPendingChoice(
                kind="mode",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=self._something_old_date(
                    artist.average_scrobble_ms
                ),
                spotify_artist=spotify_artist.name,
            ),
            (f"Choose what to add for {artist.artist}."),
        )

    def album_choice_reader(
        self,
        artist: something_old.GoldenOldieArtist,
        releases: tuple[slow_listening.DiscographyRelease, ...],
    ) -> str:
        """Read the original Something Old release selection.

        Args:
            artist: Original routine-supplied artist.
            releases: Original routine-supplied releases.

        Returns:
            The original accepted routine callback result.
        """
        return self.wait_for_submission(
            SomethingOldPendingChoice(
                kind="album",
                artist=artist.artist,
                scrobbles=artist.scrobbles,
                average_scrobble_date=self._something_old_date(
                    artist.average_scrobble_ms
                ),
                spotify_artist=self.job.result.something_old_spotify_artist,
                releases=self._something_old_release_options(releases),
            ),
            (f"Choose one album or EP by {artist.artist}."),
        )

    def interruptible_sleep(self, seconds: float) -> None:
        """Interrupt the original retry delay when this job is cancelled.

        Args:
            seconds: Original routine-supplied seconds.
        """
        if self.job.cancel_event.wait(seconds):
            raise _SomethingOldJobCancelledError

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
        self.job = self.lookup(self.job_id, command="something_old")
        with self.lock:
            self.job.result.status = "running"
            self.job.result.started_at = self.clock.now(UTC).isoformat()
            self.job.result.detail = "Something Old started"
            self.append(
                self.job,
                (
                    "Something Old started"
                    f"{(' in dry-run mode' if self.dry_run else '')}"
                    "."
                ),
            )
        self.spotify_event_setter = getattr(self.spotify, "set_event_callback", None)
        self.previous_spotify_event_callback = None
        if callable(self.spotify_event_setter):
            self.previous_spotify_event_callback = self.spotify_event_setter(self.echo)
        self.lastfm = self.create_lastfm(
            self.api_key, self.username, event_callback=self.echo
        )

    def _execute(self) -> something_old.SomethingOldSummary:
        summary = something_old.run_something_old(
            self.spotify,
            self.lastfm,
            self.playlist_id,
            expected_username=self.username,
            mode_reader=self.mode_reader,
            album_choice_reader=self.album_choice_reader,
            artist_choice_reader=self.artist_choice_reader,
            dry_run=self.dry_run,
            progress_callback=self.echo,
            retry_call=self.retry_call,
        )
        return summary

    def _completed(self, summary: something_old.SomethingOldSummary) -> None:
        ranking = self._something_old_ranking_entrys(summary)
        tracks = [self._something_old_track_result(track) for track in summary.tracks]
        with self.lock:
            self.job.result.status = (
                "cancelled" if summary.action == "cancelled" else "completed"
            )
            self.job.result.something_old_action = summary.action
            self.job.result.playlist_length_before = summary.playlist_length_before
            self.job.result.playlist_length_after = summary.playlist_length_after
            self.job.result.added = len(tracks) if summary.action == "added" else 0
            self.job.result.something_old_ranking = ranking
            self.job.result.something_old_tracks = tracks
            self.job.result.something_old_pending_choice = None
            self._present_history_and_artist(summary)
            self._present_completion_detail(summary, tracks)

    def _finish(self) -> None:
        if callable(self.spotify_event_setter):
            self.spotify_event_setter(self.previous_spotify_event_callback)
        with self.lock:
            self.job.result.something_old_pending_choice = None
            self.job.result.completed_at = self.clock.now(UTC).isoformat()

    def _cancelled(self) -> None:
        with self.lock:
            self.job.result.status = "cancelled"
            self.job.result.something_old_pending_choice = None
            self.job.result.detail = "Something Old stopped. Spotify was unchanged."
            self.append(self.job, self.job.result.detail)

    def _rate_limited(self, exc: review_album_limits.SpotifyRateLimitError) -> None:
        retry_at = None
        if exc.retry_after_seconds is not None:
            retry_at = self.clock.now(UTC) + timedelta(seconds=exc.retry_after_seconds)
        with self.lock:
            self.job.result.status = "paused"
            self.job.result.something_old_pending_choice = None
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
            self.job.result.something_old_pending_choice = None
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
            self.job.result.something_old_pending_choice = None
            self.append(self.job, self.job.result.detail)

    def _failed(
        self,
        exc: something_old.SomethingOldError
        | scrobble_history.ScrobbleHistoryError
        | LastFmError,
    ) -> None:
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.something_old_pending_choice = None
            self.job.result.detail = str(exc)
            self.append(self.job, f"Something Old failed: {exc}")

    def _unexpected_failure(self, exc: Exception) -> None:
        self.logger.exception("Unexpected Something Old error")
        with self.lock:
            self.job.result.status = "failed"
            self.job.result.something_old_pending_choice = None
            self.job.result.detail = f"Unexpected Something Old error: {exc}"
            self.append(self.job, self.job.result.detail)

    def _consume_wait_for_submission(self) -> str | None:
        with self.lock:
            if self.job.cancel_event.is_set():
                raise _SomethingOldJobCancelledError
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.something_old_pending_choice = None
            self.job.result.status = "running"
            self.job.result.detail = "Applying Something Old choice"
            self.append(self.job, f"Something Old choice received: {choice}.")
            return choice

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

    def _something_old_release_options(
        self, releases: tuple[slow_listening.DiscographyRelease, ...]
    ) -> list[SomethingOldReleaseOption]:
        entries: list[SomethingOldReleaseOption] = []
        for release in releases:
            entries.append(
                SomethingOldReleaseOption(
                    spotify_id=release.spotify_id,
                    name=release.name,
                    release_type=release.release_type,
                    release_date=release.chronology_date,
                    total_tracks=release.total_tracks,
                    saved=release.saved,
                    plain=release.plain,
                )
            )
        return entries

    def _something_old_ranking_entrys(
        self, summary: something_old.SomethingOldSummary
    ) -> list[SomethingOldRankingEntry]:
        entries: list[SomethingOldRankingEntry] = []
        for entry in summary.ranking_preview:
            entries.append(
                SomethingOldRankingEntry(
                    artist=entry.artist,
                    scrobbles=entry.scrobbles,
                    average_scrobble_date=self._something_old_date(
                        entry.average_scrobble_ms
                    ),
                )
            )
        return entries

    def _present_history_and_artist(
        self, summary: something_old.SomethingOldSummary
    ) -> None:
        if summary.history_refresh is not None:
            self.job.result.live_scrobbles_added = (
                summary.history_refresh.live_scrobbles_added
            )
            self.job.result.history_scrobbles = summary.history_refresh.total_scrobbles
        if summary.artist is not None:
            self.job.result.something_old_artist = summary.artist.artist
            self.job.result.something_old_average_scrobble_date = (
                self._something_old_date(summary.artist.average_scrobble_ms)
            )
        if summary.spotify_artist is not None:
            self.job.result.something_old_spotify_artist = summary.spotify_artist.name
        self.job.result.something_old_mode = summary.mode
        self.job.result.something_old_release = (
            summary.release.name if summary.release is not None else None
        )

    def _present_completion_detail(
        self,
        summary: something_old.SomethingOldSummary,
        tracks: list[SomethingOldTrackResult],
    ) -> None:
        if summary.action == "playlist not empty":
            self.job.result.detail = (
                "Something Old already contains "
                f"{summary.playlist_length_before}"
                " item(s); nothing was changed."
            )
        elif summary.action == "cancelled":
            self.job.result.detail = "Something Old was cancelled."
        elif summary.action == "would add":
            self.job.result.detail = (
                "Dry run: would add "
                f"{len(tracks)}"
                " track(s) for "
                f"{self.job.result.something_old_artist}"
                "."
            )
        else:
            self.job.result.detail = (
                "Added "
                f"{len(tracks)}"
                " track(s) for "
                f"{self.job.result.something_old_artist}"
                "."
            )
        for track in tracks:
            self.append(
                self.job,
                (
                    "Selected "
                    f"{', '.join(track.artists)}"
                    " - "
                    f"{track.track}"
                    " ("
                    f"{track.album or 'no album'}"
                    ")."
                ),
            )
        self.append(self.job, self.job.result.detail)
