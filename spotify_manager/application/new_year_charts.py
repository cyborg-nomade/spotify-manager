"""Synchronize annual charts before reconciling their ordered destination markers."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Literal
from typing import cast

from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.new_year_sources import named_playlist
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist


type ChartKind = Literal["tracks", "albums"]


@dataclass(frozen=True)
class AnnualCharts:
    """Bind original chart ownership, creation, membership and synchronization facts.

    Args:
        owned: Original current owned playlist reader.
        create: Original owner read and direct private-chart creation boundary.
        playlist: Original complete fresh marker facts.
        replace: Original retried exact chart replacement.
        membership: Original retry-aware destination membership reconciler.
        retry: Original caller retry around complete ensure-chart attempts.
    """

    owned: Callable[[], tuple[OwnedPlaylist, ...]]
    create: Callable[[str, ChartKind, int], str]
    playlist: Callable[[str], tuple[PlaylistTrack, ...]]
    replace: Callable[[str, list[str]], None]
    membership: AnnualMembership
    retry: RetryCall

    def run(
        self,
        plan: RetrospectivePlan,
        year: int,
        kind: ChartKind,
        limit: int,
        destination: str,
    ) -> None:
        """Ensure the chart, synchronize rank order, then add absent markers.

        Args:
            plan: Original complete resolved plan.
            year: Original source year.
            kind: Original chart category.
            limit: Original category count used only in the chart name.
            destination: Original category destination identity.
        """
        name = f"top {limit} {year} {kind}"
        playlist = cast(
            str,
            self.retry(
                partial(self._ensure, name, kind, year),
                "finding or creating yearly chart",
            ),
        )
        uris = [item["uri"] for item in plan[kind]]
        uris = list(dict.fromkeys(uris))
        current = [track.uri for track in self.playlist(playlist)]
        if current != uris:
            self.replace(playlist, uris)
        self.membership.run(destination, uris)

    def _ensure(self, name: str, kind: ChartKind, year: int) -> str:
        existing = named_playlist(self.owned(), name)
        if existing is not None:
            return existing
        return self.create(name, kind, year)
