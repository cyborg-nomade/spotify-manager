"""Read two total fields using the existing native Spotify client."""

from dataclasses import dataclass

from httpx import HTTPError
from spotipy.exceptions import SpotifyException

from spotify_manager.application.flush_mode import FlushModeCheckError
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.artist_review_values import ArtistReviewConfigError
from spotify_manager.domain.artist_review_values import parse_playlist_id
from spotify_manager.domain.flush_mode import QueueCounts


@dataclass(frozen=True)
class SpotifyQueueCounts:
    """Read counts without traversing or filtering playlist items.

    Args:
        client: Invocation-owned native Spotify client.
        queue: The Queue setting, accepting an ID, URI or share URL.
        queue_2: Queue 2 setting, accepting the same reference forms.
    """

    client: SpotifyClient
    queue: str | None
    queue_2: str | None

    async def read(self) -> QueueCounts:
        """Read both totals or report one incomplete observation.

        Returns:
            Complete live counts including unavailable playlist entries.

        Raises:
            FlushModeCheckError: Configuration, API access or totals are invalid.
        """
        try:
            first = await self._count(self.queue)
            second = await self._count(self.queue_2)
        except (ArtistReviewConfigError, SpotifyException, HTTPError, OSError) as exc:
            raise FlushModeCheckError(
                "Could not read both queue counts. The previous decision is retained."
            ) from exc
        return QueueCounts(first, second)

    async def _count(self, reference: str | None) -> int:
        if not reference:
            raise FlushModeCheckError(
                "Configure The Queue and Queue 2 before checking."
            )
        identifier = parse_playlist_id(reference)
        raw = await self.client.get(
            f"playlists/{identifier}/items", {"fields": "total", "limit": 1}
        )
        total = raw.get("total") if isinstance(raw, dict) else None
        if type(total) is not int or total < 0:
            raise FlushModeCheckError("Spotify returned an invalid playlist total.")
        return total
