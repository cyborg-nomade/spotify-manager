"""Bind the original Slow Listening SDK and persistence boundaries to ports."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.slow_listening_values import FlushResult
from spotify_manager.application.slow_listening_values import SlowListeningError
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.routines import new_wine


@dataclass
class LegacySlowListening:
    """Retain caller ownership, parsers, retry descriptions and checkpoint hooks.

    Args:
        client: Caller-owned synchronous Spotify client.
        playlist_id: Configured Slow Listening destination.
        retry: Existing retry/cancellation callback.
        state_path: Original namespace path.
        state_service: Optional explicit shared state service.
        log_path: Original audit destination.
    """

    client: Spotify
    playlist_id: str
    retry: RetryCall
    state_path: Path
    state_service: StateService | None
    log_path: Path
    _state_access: RoutineState | None = field(default=None, init=False)

    def playlist(self) -> tuple[PlaylistTrack, ...]:
        """Read live markers with the established error translation.

        Returns:
            Ordered playable playlist markers.

        Raises:
            SlowListeningError: Original shared playlist parsing fails.
        """
        from spotify_manager.routines.new_wine import load_playlist_tracks

        try:
            return load_playlist_tracks(self.client, self.playlist_id, self.retry)
        except new_wine.NewWineError as exc:
            raise SlowListeningError(str(exc)) from exc

    def load_state(self, dry_run: bool) -> dict[str, object]:
        """Resolve namespace access after the initial playlist read.

        Args:
            dry_run: Whether to use fresh defaults without reading durable state.

        Returns:
            Original namespace or preview defaults.
        """
        from spotify_manager.routines.slow_listening import _default_state
        from spotify_manager.routines.slow_listening import _state_access

        self._state_access = _state_access(self.state_path, self.state_service)
        return _default_state() if dry_run else self._state_access.load()

    def save(self, state: dict[str, object]) -> None:
        """Persist one checkpoint through the original namespace adapter.

        Args:
            state: Complete current namespace.

        Raises:
            RuntimeError: The adapter has not loaded its namespace yet.
        """
        if self._state_access is None:
            raise RuntimeError("Slow Listening state has not been loaded.")
        self._state_access.save(state)

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Read eligible studio editions with unchanged membership observations.

        Args:
            artist_id: Primary artist to read.

        Returns:
            Selected studio editions in legacy order.
        """
        from spotify_manager.routines.slow_listening import load_discography

        return load_discography(self.client, artist_id, self.retry)

    def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read playable tracks on one selected edition.

        Args:
            release: Selected studio release.

        Returns:
            Original ordered track values.
        """
        from spotify_manager.routines.slow_listening import load_release_tracks

        return load_release_tracks(self.client, release, self.retry)

    def append(self, target: ReleaseTrack) -> None:
        """Append one accepted replacement.

        Args:
            target: Selected replacement track.
        """
        from spotify_manager.routines.slow_listening import _add_playlist_track

        _add_playlist_track(self.client, self.playlist_id, target, self.retry)

    def remove(self, source: PlaylistTrack) -> None:
        """Remove one source after securing its replacement.

        Args:
            source: Original playlist marker.
        """
        from spotify_manager.routines.slow_listening import _remove_playlist_track

        _remove_playlist_track(self.client, self.playlist_id, source, self.retry)

    def audit(self, run_id: str, result: FlushResult) -> None:
        """Append the original audit record, including during previews.

        Args:
            run_id: Original execution identifier.
            result: Transition result.
        """
        from spotify_manager.routines.slow_listening import append_log

        append_log(run_id, result, self.log_path)
