"""Discovery catalog and audit bindings for the existing synchronous integrations."""

from dataclasses import dataclass
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.legacy.artist_assessment import (
    LegacyAssessmentCatalog,
)
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.your_library import YourLibraryAlbum


class LegacyDiscoveryCatalog(LegacyAssessmentCatalog):
    """Extend completion observations with ranked catalogs and works playlists.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry and cancellation callback.
    """

    def ranked(self, artist_id: str) -> tuple[RankedRelease, ...]:
        """Read the existing canonical discovery catalog.

        Args:
            artist_id: Logical artist under review.

        Returns:
            Original release observations in ranked order.
        """
        from spotify_manager.routines.new_kids import load_ranked_catalog

        return load_ranked_catalog(self.client, artist_id, self.retry)

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read the original ordered works playlist.

        Args:
            playlist_id: Accepted owned works playlist.

        Returns:
            Original playable markers, retaining duplicates.
        """
        from spotify_manager.routines.new_wine import load_playlist_tracks

        return load_playlist_tracks(self.client, playlist_id, self.retry)

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Populate shared membership observations at the original batch boundary.

        Args:
            ids: Original requested sequence, retaining duplicates.
            cache: Mutable accepted memberships shared by the review invocation.
        """
        from spotify_manager.routines.new_wine import get_liked_statuses

        get_liked_statuses(self.client, ids, cache, self.retry)


@dataclass(frozen=True)
class LegacyDiscoveryAudit:
    """Write discovery events through the original timestamp and encoding helper.

    Args:
        path: Existing per-routine audit destination.
    """

    path: Path

    def event(self, name: str, **details: object) -> None:
        """Append an original named audit record.

        Args:
            name: Existing event identifier.
            details: Original structured fields in application-supplied order.
        """
        from spotify_manager.routines.new_kids import append_event

        append_event(self.path, name, **details)


@dataclass(frozen=True)
class LegacyDiscoveryLibrary:
    """Bind discovery library effects to the existing SDK and canonical files.

    Args:
        client: Caller-owned synchronous Spotify client.
        retry: Existing retry and cancellation callback.
        albums_path: Existing local album mirror.
        removed_path: Existing removed-album recovery log.
    """

    client: Spotify
    retry: RetryCall
    albums_path: Path
    removed_path: Path

    def saved(self, release: RankedRelease) -> bool:
        """Observe saved membership through the original retry boundary.

        Args:
            release: Completed release.

        Returns:
            First truthy status, or false for an absent/malformed response.
        """
        from spotify_manager.routines.new_kids import _release_saved

        return _release_saved(self.client, release, self.retry)

    def save_album(self, release: RankedRelease) -> None:
        """Save one accepted release remotely.

        Args:
            release: Accepted release.
        """
        from spotify_manager.routines.new_kids import _save_release

        _save_release(self.client, release, self.retry)

    def remove_album(self, release: RankedRelease) -> None:
        """Remove one rejected release remotely.

        Args:
            release: Rejected release.
        """
        from spotify_manager.routines.new_kids import _remove_release

        _remove_release(self.client, release, self.retry)

    def removed_audit(
        self, release: RankedRelease, evaluation: AlbumEvaluation
    ) -> None:
        """Append the original recovery record after a successful remote removal.

        Args:
            release: Removed release.
            evaluation: Accepted live removal decision.
        """
        from spotify_manager.routines.review_album_limits import (
            append_removed_album_log,
        )

        append_removed_album_log(
            YourLibraryAlbum(
                artist=release.primary_artist_name,
                album=release.name,
                uri=release.uri,
            ),
            evaluation,
            log_path=self.removed_path,
            action="new_kids_release_boundary",
            live_liked_tracks=evaluation.liked_tracks,
        )

    def mirror(self, release: RankedRelease, should_save: bool) -> None:
        """Apply the original canonical mirror and statistics synchronization.

        Args:
            release: Completed release.
            should_save: Desired membership from the live decision.
        """
        from spotify_manager.routines.new_kids import _sync_local_album

        _sync_local_album(release, should_save, self.albums_path)
