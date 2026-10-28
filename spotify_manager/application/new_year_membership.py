"""Reconcile annual membership and top ordering inside each original retry attempt."""

from dataclasses import dataclass

from spotify_manager.application.ports.annual import AnnualPlaylist
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.domain.annual_selection import marker_position
from spotify_manager.domain.annual_selection import pending_uris


type RetryCall = Retry


@dataclass(frozen=True)
class AnnualMembership:
    """Bind original fresh membership, insertion, reorder and retry boundaries.

    Args:
        catalog: Named external catalog observations used by this stage.
        retry: Original caller retry and cancellation boundary.
    """

    catalog: AnnualPlaylist
    retry: RetryCall

    async def run(self, playlist: str, uris: list[str], top: bool = False) -> None:
        """Add unique missing markers, then restore original ranked top ordering.

        Args:
            playlist: Original destination identity.
            uris: Original ordered marker requests, including duplicate URIs.
            top: Original top-placement behavior.
        """
        unique = list(dict.fromkeys(uris))
        for offset in range(0, len(unique), 100):
            batch = unique[offset : offset + 100]
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
