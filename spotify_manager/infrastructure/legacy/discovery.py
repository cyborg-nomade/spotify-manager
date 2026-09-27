"""Discovery catalog and audit bindings for the existing synchronous integrations."""

from dataclasses import dataclass
from pathlib import Path

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.legacy.artist_assessment import (
    LegacyAssessmentCatalog,
)
from spotify_manager.routines import new_kids
from spotify_manager.routines import new_wine


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
        return new_kids.load_ranked_catalog(self.client, artist_id, self.retry)

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read the original ordered works playlist.

        Args:
            playlist_id: Accepted owned works playlist.

        Returns:
            Original playable markers, retaining duplicates.
        """
        return new_wine.load_playlist_tracks(self.client, playlist_id, self.retry)

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Populate shared membership observations at the original batch boundary.

        Args:
            ids: Original requested sequence, retaining duplicates.
            cache: Mutable accepted memberships shared by the review invocation.
        """
        new_wine.get_liked_statuses(self.client, ids, cache, self.retry)


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
        new_kids.append_event(self.path, name, **details)
