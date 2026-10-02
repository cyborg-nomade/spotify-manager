"""Coordinate original annual preflight, durable planning, preview and execution."""

from dataclasses import dataclass

from spotify_manager.application.new_year_effects import AnnualEffects
from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_execution import AnnualExecution
from spotify_manager.application.new_year_planning import AnnualPlanning
from spotify_manager.application.new_year_sources import obsessions_playlist
from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.application.new_year_values import RetrospectiveRun
from spotify_manager.application.new_year_values import RetrospectiveState


@dataclass(frozen=True)
class NewYear:
    """Bind complete original planning and accepted annual execution resources.

    Args:
        effects: Original annual preflight, state and presentation boundaries.
        planning: Original complete history/marker planning sequence.
        execution: Original five checkpointed mutation stages.
    """

    effects: AnnualEffects
    planning: AnnualPlanning
    execution: AnnualExecution

    def run(self, requested: int | None, preview: bool) -> dict[str, object]:
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
        state = access.load()
        run = state["years"].get(str(year), {"completed": []})
        if run.get("done"):
            self.effects.echo(f"The {year} retrospective has already completed.")
            return {"year": year, "already_completed": True, **run}
        plan = self._plan(year, preview, destinations, run, state, access)
        if preview:
            return self._preview(year, plan, run)
        self.execution.run(year, plan, run, state, access)
        return {"year": year, **run}

    def _plan(
        self,
        year: int,
        preview: bool,
        destinations: dict[str, str],
        run: RetrospectiveRun,
        state: RetrospectiveState,
        access: AnnualStateAccess,
    ) -> RetrospectivePlan:
        playlists = self.effects.owned()
        obsessions = obsessions_playlist(playlists, year)
        self.effects.validate_discoveries(playlists, year)
        if "plan" not in run:
            run["plan"] = self.planning.run(year, preview, destinations, obsessions)
            if not preview:
                state["years"][str(year)] = run
                access.save(state)
        plan = run["plan"]
        if plan["destinations"] != destinations:
            raise NewYearError(
                "Destination settings changed since this retrospective was planned."
            )
        return plan

    def _preview(
        self, year: int, plan: RetrospectivePlan, run: RetrospectiveRun
    ) -> dict[str, object]:
        self.effects.discoveries(year + 1, True)
        self.effects.echo(
            f"Dry run: {len(plan['tracks'])} tracks, {len(plan['albums'])} albums, "
            f"{len(plan['artists'])} artists and "
            f"{len(plan['obsessions'])} Obsessions tracks."
        )
        return {"year": year, "dry_run": True, **run}
