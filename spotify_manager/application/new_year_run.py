"""Coordinate original annual preflight, durable planning, preview and execution."""

from dataclasses import dataclass

from spotify_manager.application.new_year_discoveries import AnnualDiscoveries
from spotify_manager.application.new_year_effects import AnnualEffects
from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_execution import AnnualExecution
from spotify_manager.application.new_year_planning import AnnualPlanning
from spotify_manager.application.new_year_sources import obsessions_playlist
from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.application.new_year_values import RetrospectiveRun
from spotify_manager.application.new_year_values import RetrospectiveState
from spotify_manager.application.queue_3_import import resolve_yearly_playlist
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.annual_history import is_dropped


@dataclass(frozen=True)
class NewYear:
    """Bind complete original planning and accepted annual execution resources.

    Args:
        effects: Original annual preflight, state and presentation boundaries.
        planning: Original complete history/marker planning sequence.
        execution: Original five checkpointed mutation stages.
        discoveries: Named annual discovery import stage.
    """

    effects: AnnualEffects
    planning: AnnualPlanning
    execution: AnnualExecution
    discoveries: AnnualDiscoveries

    async def run(self, requested: int | None, preview: bool) -> dict[str, object]:
        """Validate source year, reuse durable plans and execute original annual stages.

        Args:
            requested: Original optional completed source year.
            preview: Original preview behavior including history and discovery reads.

        Returns:
            Original wide result retaining unknown fields and stored key overrides.

        Raises:
            NewYearError: Original year, source, marker or destination authority fails.
        """
        current = self.effects.clock().year
        year = requested if requested is not None else current - 1
        if year < 2002 or year >= current:
            raise NewYearError("Choose a completed calendar year (2002 or later).")
        destinations = self.effects.destinations()
        access = self.effects.state()
        state = await access.load()
        run = state["years"].get(str(year), {"completed": []})
        if run.get("done"):
            self.effects.echo(f"The {year} retrospective has already completed.")
            return {"year": year, "already_completed": True, **run}
        plan = await self._plan(year, preview, destinations, run, state, access)
        if preview:
            return await self._preview(year, plan, run)
        await self.execution.run(year, plan, run, state, access)
        return {"year": year, **run}

    async def _plan(
        self,
        year: int,
        preview: bool,
        destinations: dict[str, str],
        run: RetrospectiveRun,
        state: RetrospectiveState,
        access: AnnualStateAccess,
    ) -> RetrospectivePlan:
        playlists = await self.effects.owned()
        obsessions = obsessions_playlist(playlists, year)
        resolve_yearly_playlist(playlists, year)
        if "plan" not in run:
            run["plan"] = await self.planning.run(
                year, preview, destinations, obsessions
            )
            if not preview:
                state["years"][str(year)] = run
                await access.save(state)
        plan = run["plan"]
        if plan["destinations"] != destinations:
            raise NewYearError(
                "Destination settings changed since this retrospective was planned."
            )
        return plan

    async def _preview(
        self, year: int, plan: RetrospectivePlan, run: RetrospectiveRun
    ) -> dict[str, object]:
        await self.discoveries.run(year + 1, True)
        self.effects.echo(
            f"Dry run: {_accepted_count(plan['tracks'])} tracks, "
            f"{_accepted_count(plan['albums'])} albums, "
            f"{_accepted_count(plan['artists'])} artists and "
            f"{len(plan['obsessions'])} Obsessions tracks."
        )
        dropped = _dropped_count(plan)
        if dropped:
            self.effects.echo(
                f"Explicitly dropped {dropped} unresolved entries; "
                "accepted markers remain in rank order."
            )
        return {"year": year, "dry_run": True, **run}


def _accepted_count(items: list[YearEntry]) -> int:
    return sum(not is_dropped(item) for item in items)


def _dropped_count(plan: RetrospectivePlan) -> int:
    total = 0
    for kind in ("tracks", "albums", "artists"):
        total += len(plan[kind]) - _accepted_count(plan[kind])
    return total
