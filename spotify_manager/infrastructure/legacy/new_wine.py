"""Bind New Wine ports to the established synchronous integration boundaries."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
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
        return legacy.load_playlist_tracks(self.client, playlist_id, self.retry)

    def load_state(self, dry_run: bool) -> dict[str, object]:
        """Resolve namespace access after both initial playlist reads.

        Args:
            dry_run: Whether to use fresh defaults without reading durable state.

        Returns:
            Existing namespace or original preview defaults.
        """
        self._state_access = legacy._state_access(self.state_path, self.state_service)
        return legacy._default_state() if dry_run else self._state_access.load()

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
        return legacy.load_release_tracks(self.client, release, self.retry)

    def releases(self, artist_id: str, year: int) -> tuple[ReleaseCandidate, ...]:
        """Read current-year primary-credit candidates.

        Args:
            artist_id: Source marker's primary artist.
            year: Existing active year.

        Returns:
            Original ordered release candidates.
        """
        return legacy.current_year_releases(self.client, artist_id, year, self.retry)

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Fill missing likes under the original batching and validation rules.

        Args:
            ids: Requested track IDs in order.
            cache: Run-scoped membership cache updated in place.
        """
        legacy.get_liked_statuses(self.client, ids, cache, self.retry)

    def append(self, playlist_id: str, track: ReleaseTrack) -> None:
        """Append a replacement with the original retry description.

        Args:
            playlist_id: Destination playlist.
            track: Accepted replacement.
        """
        legacy._add_playlist_track(self.client, playlist_id, track, self.retry)

    def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Remove a source after required additions.

        Args:
            playlist_id: Source playlist.
            source: Original marker.
        """
        legacy._remove_playlist_track(self.client, playlist_id, source, self.retry)

    def saved(self, release: ReleaseCandidate, *, removing: bool = False) -> bool:
        """Retain each original saved-membership SDK boundary and parser.

        Args:
            release: Selected release.
            removing: Whether the observation belongs to the drop workflow.

        Returns:
            Original tolerant first-status interpretation.
        """
        reader = legacy._saved_for_drop if removing else legacy._saved_for_keep
        return reader(self.client, release, self.retry)

    def save_album(self, release: ReleaseCandidate) -> None:
        """Save a qualifying album remotely.

        Args:
            release: Selected album.
        """
        legacy._save_album(self.client, release, self.retry)

    def unsave_album(self, release: ReleaseCandidate) -> None:
        """Unsave a rejected album remotely.

        Args:
            release: Selected album.
        """
        legacy._unsave_album(self.client, release, self.retry)

    def mirror_album(self, release: ReleaseCandidate) -> None:
        """Publish a qualifying album through the existing mirror/statistics helper.

        Args:
            release: Accepted album.
        """
        legacy._add_local_album(release, self.albums_path)

    def remove_mirror_album(self, release: ReleaseCandidate) -> None:
        """Publish removal through the existing mirror/statistics helper.

        Args:
            release: Album already unsaved remotely.
        """
        legacy._remove_local_album(release.spotify_id, self.albums_path)

    def removed_audit(
        self, release: ReleaseCandidate, evaluation: AlbumEvaluation, reason: str
    ) -> None:
        """Append the original album-recovery record after mirror removal.

        Args:
            release: Removed album.
            evaluation: Original live keep evaluation.
            reason: Original drop action identifier.
        """
        legacy.append_removed_album_log(
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
        legacy.append_log(run_id, result, self.log_path)

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
        return legacy._refill_new_wine(
            self.client,
            self.destination,
            cellar_id,
            no_discovery=no_discovery,
            dry_run=dry_run,
            retry_call=self.retry,
            state=state,
            run=run,
            state_access=self._state(),
            log_path=self.log_path,
            liked_tracks_path=self.liked_path,
            albums_path=self.albums_path,
            echo=self.echo,
            projected_new_wine_ids=projected,
        )
