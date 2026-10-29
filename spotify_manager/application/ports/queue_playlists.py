"""Named Queue 3 playlist, audit and studio-catalog boundaries."""

from collections.abc import Sequence
from typing import Protocol

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack


class PlaylistAppend(Protocol):
    """Accept an original ordered marker batch."""

    async def append(
        self, playlist_id: str, tracks: list[PlaylistTrack], description: str
    ) -> None:
        """Append accepted markers with the original retry description.

        Args:
            playlist_id: Original destination identity.
            tracks: Original ordered marker batch.
            description: Original retry context.
        """


class PlaylistWrites(PlaylistAppend, Protocol):
    """Accept original marker additions and removals."""

    async def remove(self, playlist_id: str, uris: list[str], description: str) -> None:
        """Remove the original marker batch.

        Args:
            playlist_id: Original destination identity.
            uris: Original ordered marker URIs.
            description: Original retry context.
        """


class QueueAudit(Protocol):
    """Append accepted Queue 3 decisions at their original audit boundary."""

    async def audit(self, event: str, details: dict[str, object]) -> None:
        """Append the original structured event.

        Args:
            event: Original event identifier.
            details: Original fields in insertion order.
        """


class ImportAccess(PlaylistAppend, QueueAudit, Protocol):
    """Read annual source markers and accept their import effects."""

    async def read(self, playlist_id: str) -> Sequence[PlaylistTrack]:
        """Observe original complete annual markers.

        Args:
            playlist_id: Original annual source identity.

        Returns:
            Original complete ordered source markers.
        """


class WorksRead(Protocol):
    """Observe original complete works-playlist markers."""

    async def read(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read an owned works playlist without executing a review stage.

        Args:
            playlist_id: Original accepted owned playlist identity.

        Returns:
            Original complete parsed markers in encounter order.
        """


class StudioCatalog(Protocol):
    """Observe an artist's original chronological studio releases."""

    async def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Read eligible studio releases.

        Args:
            artist_id: Original logical artist identity.

        Returns:
            Original chronological selected editions.
        """
