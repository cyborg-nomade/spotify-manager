"""Bind Queue 3 playlist and audit effects to the existing compatibility helpers."""

from dataclasses import dataclass
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.queue_3_values import Queue3Error
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.routines import new_wine


@dataclass(frozen=True)
class LegacyAnnualImport:
    """Retain Spotify retries, error translation, batching and audit storage.

    Args:
        client: Caller-owned Spotify client.
        retry: Existing request retry and cancellation boundary.
        log_path: Original audit destination.
    """

    client: Spotify
    retry: RetryCall
    log_path: Path

    def read(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read source markers and translate the original playlist error.

        Args:
            playlist_id: Previous-year discovery playlist identifier.

        Returns:
            Parsed markers in source order.

        Raises:
            Queue3Error: The existing playlist reader fails.
        """
        from spotify_manager.routines.new_wine import load_playlist_tracks

        try:
            return load_playlist_tracks(self.client, playlist_id, self.retry)
        except new_wine.NewWineError as exc:
            raise Queue3Error(str(exc)) from exc

    def append(
        self, playlist_id: str, tracks: list[PlaylistTrack], description: str
    ) -> None:
        """Append markers through the original ordered batch helper.

        Args:
            playlist_id: Destination Queue 3 identifier.
            tracks: Selected artist markers in source order.
            description: Original retry description before batch suffixes.
        """
        from spotify_manager.routines.queue_3 import _add_playlist_tracks

        _add_playlist_tracks(self.client, playlist_id, tracks, self.retry, description)

    def audit(self, event: str, details: dict[str, object]) -> None:
        """Persist original audit fields at the caller's audit destination.

        Args:
            event: Original event identifier.
            details: Original structured event fields.
        """
        from spotify_manager.routines.queue_3 import append_event

        append_event(self.log_path, event, **details)

    def remove(self, playlist_id: str, uris: list[str], description: str) -> None:
        """Remove markers through original URI deduplication and ordered batches.

        Args:
            playlist_id: Queue 3 destination.
            uris: Original marker URI selection.
            description: Original retry message before batch suffixes.
        """
        from spotify_manager.routines.queue_3 import _remove_playlist_uris

        _remove_playlist_uris(self.client, playlist_id, uris, self.retry, description)


@dataclass(frozen=True)
class LegacyQueue3Catalog:
    """Read chronological tracks and live memberships through existing adapters.

    Args:
        client: Caller-owned Spotify client.
        retry: Existing request retry and cancellation boundary.
        liked: Caller-owned live membership cache for the current run.
    """

    client: Spotify
    retry: RetryCall
    liked: dict[str, bool]

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Read chronological eligible editions through the original catalog loader.

        Args:
            artist_id: Original logical artist identifier.

        Returns:
            Selected studio releases in original chronological order.
        """
        from spotify_manager.routines.slow_listening import load_discography

        return load_discography(self.client, artist_id, self.retry)

    def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read a selected edition through the original ordered-track loader.

        Args:
            release: Preferred studio edition.

        Returns:
            Original playable tracks in disc and track order.
        """
        from spotify_manager.routines.slow_listening import load_release_tracks

        return load_release_tracks(self.client, release, self.retry)

    def evaluate(
        self, release: DiscographyRelease, tracks: tuple[ReleaseTrack, ...]
    ) -> AlbumEvaluation:
        """Observe live liked statuses before evaluating a completed edition.

        Args:
            release: Completed preferred edition.
            tracks: Previously observed complete ordered track list.

        Returns:
            Original album evaluation with per-track live memberships.
        """
        from spotify_manager.application.release_evaluation import evaluate_release
        from spotify_manager.domain.catalog import release_candidate
        from spotify_manager.routines.new_wine import get_liked_statuses

        get_liked_statuses(
            self.client,
            [track.spotify_id for track in tracks],
            self.liked,
            self.retry,
        )
        return evaluate_release(release_candidate(release), tracks, self.liked)
