"""Reconcile annual membership and top ordering inside each original retry attempt."""

from dataclasses import dataclass

from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.application.ports.annual import AnnualPlaylist
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.domain.annual_selection import marker_position
from spotify_manager.domain.annual_selection import pending_uris


type RetryCall = Retry

_APPEND_BATCH_SIZE = 100


@dataclass(frozen=True)
class AnnualMembership:
    """Bind original fresh membership, insertion, reorder and retry boundaries.

    Args:
        catalog: Named external catalog observations used by this stage.
        retry: Original caller retry and cancellation boundary.
    """

    catalog: AnnualPlaylist
    retry: RetryCall

    async def playlist_length(self, playlist: str) -> int:
        """Count playable items before the first append.

        Args:
            playlist: Destination playlist identity.

        Returns:
            Number of playable items in the current playlist.
        """
        return len(await self.catalog.playlist(playlist))

    async def append_ordered(self, playlist: str, uris: list[str], start: int) -> None:
        """Append every occurrence and reconcile retries against the saved start.

        Args:
            playlist: Destination playlist identity.
            uris: Complete ordered sequence to append.
            start: Count of playable items before this step first wrote to Spotify.

        Raises:
            NewYearError: The playlist changed and the append cannot safely resume.
        """
        for offset in range(0, len(uris), _APPEND_BATCH_SIZE):
            await self._append_ordered_batch(playlist, uris, start, offset)

    async def _append_ordered_batch(
        self, playlist: str, uris: list[str], start: int, offset: int
    ) -> None:
        for attempt in self.retry.attempts("appending ordered retrospective tracks"):
            async with attempt:
                await self._append_missing_suffix(playlist, uris, start, offset)

    async def _append_missing_suffix(
        self, playlist: str, uris: list[str], start: int, offset: int
    ) -> None:
        tracks = await self.catalog.playlist(playlist)
        appended = [track.uri for track in tracks[start:]]
        if len(tracks) < start + offset or appended != uris[: len(appended)]:
            raise NewYearError(
                "The Blast from the Past playlist changed during the retrospective. "
                "Restore the playlist to its expected order before resuming."
            )
        missing = uris[len(appended) : offset + _APPEND_BATCH_SIZE]
        if missing:
            await self.catalog.append_once(playlist, missing)

    async def run(self, playlist: str, uris: list[str], top: bool = False) -> None:
        """Add unique missing markers, then restore original ranked top ordering.

        Args:
            playlist: Original destination identity.
            uris: Original ordered marker requests, including duplicate URIs.
            top: Original top-placement behavior.
        """
        unique = list(dict.fromkeys(uris))
        for offset in range(0, len(unique), _APPEND_BATCH_SIZE):
            batch = unique[offset : offset + _APPEND_BATCH_SIZE]
            await self._add(playlist, batch, top)
        if not top:
            return
        for uri in reversed(unique):
            await self._move(playlist, uri)

    async def _add(self, playlist: str, batch: list[str], top: bool) -> None:
        for attempt in self.retry.attempts("adding retrospective tracks"):
            async with attempt:
                await self._add_attempt(playlist, batch, top)

    async def _add_attempt(self, playlist: str, batch: list[str], top: bool) -> None:
        existing = await self.catalog.playlist(playlist)
        pending = pending_uris(batch, existing)
        if pending:
            await self.catalog.append(playlist, pending, top)

    async def _move(self, playlist: str, uri: str) -> None:
        description = "placing yearly artists at the top of Memory Lane"
        for attempt in self.retry.attempts(description):
            async with attempt:
                await self._move_attempt(playlist, uri)

    async def _move_attempt(self, playlist: str, uri: str) -> None:
        live = await self.catalog.playlist(playlist)
        position = marker_position(live, uri)
        if position:
            await self.catalog.move(playlist, position)
