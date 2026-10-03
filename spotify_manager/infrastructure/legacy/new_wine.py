"""Bind New Wine ports to the established synchronous integration boundaries."""

from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.wine_cellar import CellarOptions
from spotify_manager.application.wine_cellar import refill_cellar
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.infrastructure.legacy.wine_cellar import WineCellarAccess
from spotify_manager.interfaces.presenters.wine_cellar import present_transfer
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.routines import new_wine as legacy


@dataclass
class LegacyNewWine:
    """Retain caller-owned integrations, canonical mirrors and persistence hooks.

    Args:
        client: Caller-owned synchronous Spotify client.
        destination: New Wine playlist identifier.
        retry: Existing retry/cancellation callback.
        state_path: Original namespace path.
        state_service: Optional shared namespace service.
        log_path: Original audit destination.
        albums_path: Canonical saved-album mirror.
        liked_path: Canonical liked-track mirror.
        removed_path: Removed-album recovery log.
        echo: Existing message sink used by cellar composition.
    """

    client: Spotify
    destination: str
    retry: RetryCall
    state_path: Path
    state_service: StateService | None
    log_path: Path
    albums_path: Path
    liked_path: Path
    removed_path: Path
    echo: legacy.Echo
    _state_access: RoutineState | None = field(default=None, init=False)

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read original ordered playlist observations.

        Args:
            playlist_id: Source or destination identifier.

        Returns:
            Parsed playable markers.
        """
        from spotify_manager.routines.new_wine import load_playlist_tracks

        return load_playlist_tracks(self.client, playlist_id, self.retry)

    def load_state(self, dry_run: bool) -> dict[str, object]:
        """Resolve namespace access after both initial playlist reads.

        Args:
            dry_run: Whether to use fresh defaults without reading durable state.

        Returns:
            Existing namespace or original preview defaults.
        """
        from spotify_manager.routines.new_wine import _default_state
        from spotify_manager.routines.new_wine import _state_access

        self._state_access = _state_access(self.state_path, self.state_service)
        return _default_state() if dry_run else self._state_access.load()

    def _state(self) -> RoutineState:
        if self._state_access is None:
            raise RuntimeError("New Wine state has not been loaded.")
        return self._state_access

    def save(self, state: dict[str, object]) -> None:
        """Persist one namespace checkpoint.

        Args:
            state: Complete mutable namespace.
        """
        self._state().save(state)

    def tracks(self, release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        """Read selected release tracks with original parsing.

        Args:
            release: Selected release.

        Returns:
            Ordered playable tracks.
        """
        from spotify_manager.routines.new_wine import load_release_tracks

        return load_release_tracks(self.client, release, self.retry)

    def releases(self, artist_id: str, year: int) -> tuple[ReleaseCandidate, ...]:
        """Read current-year primary-credit candidates.

        Args:
            artist_id: Source marker's primary artist.
            year: Existing active year.

        Returns:
            Original ordered release candidates.
        """
        from spotify_manager.routines.new_wine import current_year_releases

        return current_year_releases(self.client, artist_id, year, self.retry)

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Fill missing likes under the original batching and validation rules.

        Args:
            ids: Requested track IDs in order.
            cache: Run-scoped membership cache updated in place.
        """
        from spotify_manager.routines.new_wine import get_liked_statuses

        get_liked_statuses(self.client, ids, cache, self.retry)

    def append(self, playlist_id: str, track: ReleaseTrack) -> None:
        """Append a replacement with the original retry description.

        Args:
            playlist_id: Destination playlist.
            track: Accepted replacement.
        """
        from spotify_manager.routines.new_wine import _add_playlist_track

        _add_playlist_track(self.client, playlist_id, track, self.retry)

    def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Remove a source after required additions.

        Args:
            playlist_id: Source playlist.
            source: Original marker.
        """
        from spotify_manager.routines.new_wine import _remove_playlist_track

        _remove_playlist_track(self.client, playlist_id, source, self.retry)

    def saved(self, release: ReleaseCandidate, *, removing: bool = False) -> bool:
        """Retain each original saved-membership SDK boundary and parser.

        Args:
            release: Selected release.
            removing: Whether the observation belongs to the drop workflow.

        Returns:
            Original tolerant first-status interpretation.
        """
        from spotify_manager.routines.new_wine import _saved_for_drop
        from spotify_manager.routines.new_wine import _saved_for_keep

        reader = _saved_for_drop if removing else _saved_for_keep
        return reader(self.client, release, self.retry)

    def save_album(self, release: ReleaseCandidate) -> None:
        """Save a qualifying album remotely.

        Args:
            release: Selected album.
        """
        from spotify_manager.routines.new_wine import _save_album

        _save_album(self.client, release, self.retry)

    def unsave_album(self, release: ReleaseCandidate) -> None:
        """Unsave a rejected album remotely.

        Args:
            release: Selected album.
        """
        from spotify_manager.routines.new_wine import _unsave_album

        _unsave_album(self.client, release, self.retry)

    def mirror_album(self, release: ReleaseCandidate) -> None:
        """Publish a qualifying album through the existing mirror/statistics helper.

        Args:
            release: Accepted album.
        """
        from spotify_manager.routines.new_wine import _add_local_album

        _add_local_album(release, self.albums_path)

    def remove_mirror_album(self, release: ReleaseCandidate) -> None:
        """Publish removal through the existing mirror/statistics helper.

        Args:
            release: Album already unsaved remotely.
        """
        from spotify_manager.routines.new_wine import _remove_local_album

        _remove_local_album(release.spotify_id, self.albums_path)

    def removed_audit(
        self, release: ReleaseCandidate, evaluation: AlbumEvaluation, reason: str
    ) -> None:
        """Append the original album-recovery record after mirror removal.

        Args:
            release: Removed album.
            evaluation: Original live keep evaluation.
            reason: Original drop action identifier.
        """
        from spotify_manager.routines.review_album_limits import (
            append_removed_album_log,
        )

        append_removed_album_log(
            album=YourLibraryAlbum(
                artist=release.primary_artist_name, album=release.name, uri=release.uri
            ),
            evaluation=evaluation,
            log_path=self.removed_path,
            action=reason,
            live_liked_tracks=evaluation.liked_tracks,
        )

    def audit(self, run_id: str, result: FlushResult) -> None:
        """Append the original New Wine audit result.

        Args:
            run_id: Original execution identifier.
            result: Completed or skipped result, including previews.
        """
        from spotify_manager.routines.new_wine import append_log

        append_log(run_id, result, self.log_path)

    def refill(
        self,
        cellar_id: str,
        no_discovery: bool,
        dry_run: bool,
        state: dict[str, object],
        run: dict[str, object],
        projected: set[str] | None,
    ) -> CellarRefillSummary:
        """Bind the established cellar use case at the original refill boundary.

        Args:
            cellar_id: Effective cellar source.
            no_discovery: Effective affinity requirement.
            dry_run: Whether to preview transfers.
            state: Complete namespace.
            run: Active run inside the namespace.
            projected: Preview destination membership after the flush.

        Returns:
            Original refill result.
        """
        options = CellarOptions(
            self.destination,
            cellar_id,
            no_discovery,
            dry_run,
            legacy.NEW_WINE_TARGET_SIZE,
            projected,
        )
        access = self._state()
        integration = WineCellarAccess(
            self.client,
            self.retry,
            access,
            self.log_path,
            self.liked_path,
            self.albums_path,
        )
        return refill_cellar(
            integration, options, state, run, partial(present_transfer, self.echo)
        )
