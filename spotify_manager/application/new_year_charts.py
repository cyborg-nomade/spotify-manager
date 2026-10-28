"""Synchronize annual charts before reconciling their ordered destination markers."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.new_year_sources import named_playlist
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.application.ports.annual import AnnualChartCatalog


type ChartKind = Literal["tracks", "albums"]


@dataclass(frozen=True)
class AnnualCharts:
    """Bind original chart ownership, creation, membership and synchronization facts.

    Args:
        catalog: Named external catalog observations used by this stage.
        membership: Original retry-aware destination membership reconciler.
        retry: Original caller retry around complete ensure-chart attempts.
    """

    catalog: AnnualChartCatalog
    membership: AnnualMembership
    retry: RetryCall

    async def run(
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
        for attempt in self.retry.attempts("finding or creating yearly chart"):
            async with attempt:
                response = await self._ensure(name, kind, year)
        playlist = response
        uris = [item["uri"] for item in plan[kind]]
        uris = list(dict.fromkeys(uris))
        current = [track.uri for track in (await self.catalog.playlist(playlist))]
        if current != uris:
            await self.catalog.replace(playlist, uris)
        await self.membership.run(destination, uris)

    async def _ensure(self, name: str, kind: ChartKind, year: int) -> str:
        existing = named_playlist((await self.catalog.owned()), name)
        if existing is not None:
            return existing
        return await self.catalog.create(name, kind, year)
