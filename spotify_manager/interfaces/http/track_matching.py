"""Own web matching interactions and validate submissions under the job lock."""

from dataclasses import dataclass
from uuid import uuid4

from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.manual_matching import ManualAlbumCandidate
from spotify_manager.interfaces.http.job_records import PlaylistJob
from spotify_manager.interfaces.http.models.track_matching import AlbumMatchOption
from spotify_manager.interfaces.http.models.track_matching import TrackMatchOption
from spotify_manager.interfaces.http.models.track_matching import (
    TrackMatchPendingChoice,
)
from spotify_manager.interfaces.http.playlist_context import PlaylistContext


def _options(candidates: tuple[SpotifyTrackMatch, ...]) -> list[TrackMatchOption]:
    options = []
    for candidate in candidates:
        options.append(
            TrackMatchOption(
                spotify_id=candidate.spotify_id,
                track=candidate.track,
                artists=list(candidate.artists),
                album=candidate.album,
                url=f"https://open.spotify.com/track/{candidate.spotify_id}",
            )
        )
    return options


def _album_options(
    candidates: tuple[ManualAlbumCandidate, ...],
) -> list[AlbumMatchOption]:
    options = []
    for candidate in candidates:
        options.append(
            AlbumMatchOption(
                spotify_id=candidate.spotify_id,
                album=candidate.album,
                artists=list(candidate.artists),
                release_type=candidate.release_type,
                release_date=candidate.release_date,
                url=f"https://open.spotify.com/album/{candidate.spotify_id}",
            )
        )
    return options


@dataclass(frozen=True)
class WebCatalogMatching:
    """Publish one pending choice and consume only this job's accepted submission.

    Args:
        context: Shared registry lock and log presenter.
        job: Invocation-owned record and interaction signals.
    """

    context: PlaylistContext
    job: PlaylistJob

    async def choose(
        self, scrobble: Scrobble, candidates: tuple[SpotifyTrackMatch, ...]
    ) -> str:
        """Present candidates, including an empty result, and await a decision.

        Args:
            scrobble: Historical play being resolved.
            candidates: Search results in their original order.

        Returns:
            Selected ID, or an empty string for no match.

        Raises:
            BlastFromPastCancelledError: The job is cancelled before consumption.
        """
        pending = TrackMatchPendingChoice(
            request_id=str(uuid4()),
            scrobble=(
                f"{scrobble.artist} - {scrobble.track} - "
                f"{scrobble.album or '(no album)'}"
            ),
            candidates=_options(candidates),
        )
        return await self._wait(pending)

    async def choose_album_match(
        self, scrobble: Scrobble, candidates: tuple[ManualAlbumCandidate, ...]
    ) -> str:
        """Present release candidates using the same reconnectable choice channel.

        Args:
            scrobble: Original unresolved historical reference.
            candidates: Album observations in Spotify search order.

        Returns:
            Selected album ID, or an empty string for no match.

        Raises:
            BlastFromPastCancelledError: Cancellation wins before consumption.
        """
        pending = TrackMatchPendingChoice(
            request_id=str(uuid4()),
            scrobble=f"{scrobble.artist} - {scrobble.track or scrobble.album}",
            candidates=[],
            kind="album",
            albums=_album_options(candidates),
        )
        return await self._wait(pending)

    async def _wait(self, pending: TrackMatchPendingChoice) -> str:
        with self.context.lock:
            self._check_cancel()
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.track_match_pending_choice = pending
            self.job.result.status = "waiting"
            self.job.result.detail = "Choose a Spotify match or select No match"
            self.context.append(self.job, self.job.result.detail)
        return await await_submission(self.job.choice_event, self)

    def check(self) -> None:
        """Check cancellation under the same lock as choice consumption.

        Raises:
            BlastFromPastCancelledError: The invocation has been cancelled.
        """
        with self.context.lock:
            self._check_cancel()

    def _check_cancel(self) -> None:
        if self.job.cancel_event.is_set():
            self.job.result.track_match_pending_choice = None
            raise BlastFromPastCancelledError("Manual track matching was cancelled.")

    def consume(self) -> str | None:
        """Consume a submission under the lock, giving cancellation precedence.

        Returns:
            Submitted ID or rejection, or none while waiting.

        Raises:
            BlastFromPastCancelledError: Cancellation is requested.
        """
        with self.context.lock:
            self._check_cancel()
            choice = self.job.submitted_choice
            if choice is None:
                return None
            self.job.submitted_choice = None
            self.job.choice_event.clear()
            self.job.result.track_match_pending_choice = None
            self.job.result.status = "running"
            self.context.append(
                self.job, f"Manual Spotify match: {choice or 'no match'}."
            )
            return choice


WebTrackMatching = WebCatalogMatching
