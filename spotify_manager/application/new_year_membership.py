"""Reconcile annual membership and top ordering inside each original retry attempt."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from spotify_manager.application.ports.annual import AnnualPlaylist
from spotify_manager.domain.annual_selection import marker_position
from spotify_manager.domain.annual_selection import pending_uris


type RetryCall = Callable[[Callable[[], object], str], object]


@dataclass(frozen=True)
class AnnualMembership:
    """Bind original fresh membership, insertion, reorder and retry boundaries.

    Args:
        catalog: Named external catalog observations used by this stage.
        retry: Original caller retry and cancellation boundary.
    """

    catalog: AnnualPlaylist
    retry: RetryCall

    def run(self, playlist: str, uris: list[str], top: bool = False) -> None:
        """Add unique missing markers, then restore original ranked top ordering.

        Args:
            playlist: Original destination identity.
            uris: Original ordered marker requests, including duplicate URIs.
            top: Original top-placement behavior.
        """
        unique = list(dict.fromkeys(uris))
        for offset in range(0, len(unique), 100):
            batch = unique[offset : offset + 100]
            self.retry(
                partial(self._add, playlist, batch, top), "adding retrospective tracks"
            )
        if not top:
            return
        for uri in reversed(unique):
            self.retry(
                partial(self._move, playlist, uri),
                "placing yearly artists at the top of Memory Lane",
            )

    def _add(self, playlist: str, batch: list[str], top: bool) -> None:
        existing = self.catalog.playlist(playlist)
        pending = pending_uris(batch, existing)
        if pending:
            self.catalog.append(playlist, pending, top)

    def _move(self, playlist: str, uri: str) -> None:
        live = self.catalog.playlist(playlist)
        position = marker_position(live, uri)
        if position:
            self.catalog.move(playlist, position)
