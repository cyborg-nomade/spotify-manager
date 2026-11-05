"""Read exact operator-supplied album editions through the existing Spotify client."""

from dataclasses import dataclass
from dataclasses import replace

from spotipy.exceptions import SpotifyException

from spotify_manager.application.discography_values import DiscographyAlbumError
from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.discography_links import ReviewRelease
from spotify_manager.infrastructure.discography_records import linked_release


@dataclass(frozen=True)
class DiscographyLinkedAlbums:
    """Own exact metadata and saved-status reads, without constructing clients.

    Args:
        spotify: Invocation-owned Spotify client.
        retry: Existing owning interface's retry/cancellation policy.
    """

    spotify: SpotifyClient
    retry: RetryCall

    async def album(self, identity: str) -> ReviewRelease:
        """Resolve an exact album without canonical or primary-credit filters.

        Args:
            identity: Validated album identifier.

        Returns:
            Checked metadata, credits and saved status for this precise edition.

        Raises:
            DiscographyAlbumError: Album unavailable or observations invalid.
            SpotifyException: A different failure must reach the owning policy.
        """
        try:
            raw = await self._metadata(identity)
        except SpotifyException as exc:
            if exc.http_status not in {404, 410}:
                raise
            raise DiscographyAlbumError("Spotify could not find this album.") from exc
        entry = linked_release(raw, identity)
        saved = await self._saved(identity)
        return replace(entry, release=replace(entry.release, saved=saved))

    async def _metadata(self, identity: str) -> object:
        for attempt in self.retry.attempts("loading linked discography album"):
            async with attempt:
                return await self.spotify.album(identity)
        raise AssertionError("The retry policy did not attempt album metadata.")

    async def _saved(self, identity: str) -> bool:
        for attempt in self.retry.attempts("checking linked discography album"):
            async with attempt:
                raw = await self.spotify.current_user_saved_albums_contains([identity])
                return _saved_status(raw)
        raise AssertionError("The retry policy did not attempt saved status.")


def _saved_status(raw: object) -> bool:
    if not isinstance(raw, list) or len(raw) != 1 or type(raw[0]) is not bool:
        raise DiscographyAlbumError("Spotify returned invalid saved-album status.")
    return raw[0]
