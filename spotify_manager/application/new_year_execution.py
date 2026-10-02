"""Execute the original five annual steps with per-step accepted checkpoints."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from spotify_manager.application.new_year_charts import AnnualCharts
from spotify_manager.application.new_year_charts import ChartKind
from spotify_manager.application.new_year_effects import AnnualEffects
from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.application.new_year_values import RetrospectiveRun
from spotify_manager.application.new_year_values import RetrospectiveState


@dataclass(frozen=True)
class AnnualExecution:
    """Bind original charts, membership, discovery effects and completion authority.

    Args:
        effects: Original cancellation, discovery and presentation resources.
        charts: Original category chart synchronization.
        membership: Original retry-aware destination reconciliation.
    """

    effects: AnnualEffects
    charts: AnnualCharts
    membership: AnnualMembership

    def run(
        self,
        year: int,
        plan: RetrospectivePlan,
        run: RetrospectiveRun,
        state: RetrospectiveState,
        access: AnnualStateAccess,
    ) -> None:
        """Apply the five annual categories in original order.

        Args:
            year: Original source year.
            plan: Original complete durable plan.
            run: Original mutable annual completion authority.
            state: Original complete namespace.
            access: Original accepted durable write boundary.
        """
        steps = self._steps(year, plan)
        for step, operation in steps:
            self._checkpoint(step, operation, run, state, access)
        run["done"] = True
        access.save(state)
        self.effects.echo(f"The {year} retrospective is complete.")

    def _steps(
        self, year: int, plan: RetrospectivePlan
    ) -> tuple[tuple[str, Callable[[], None]], ...]:
        return (
            ("top tracks", partial(self._chart, plan, year, "tracks", 50, "blast")),
            ("top albums", partial(self._chart, plan, year, "albums", 20, "palace")),
            ("top artists", partial(self._artists, plan)),
            ("Great Discoveries", partial(self.effects.discoveries, year + 1, False)),
            ("Obsessions", partial(self._obsessions, plan)),
        )

    def _chart(
        self,
        plan: RetrospectivePlan,
        year: int,
        kind: ChartKind,
        limit: int,
        destination: str,
    ) -> None:
        self.charts.run(plan, year, kind, limit, plan["destinations"][destination])

    def _artists(self, plan: RetrospectivePlan) -> None:
        uris = [item["uri"] for item in plan["artists"]]
        self.membership.run(plan["destinations"]["memory"], uris, True)

    def _obsessions(self, plan: RetrospectivePlan) -> None:
        self.membership.run(plan["destinations"]["blast"], plan["obsessions"])

    def _checkpoint(
        self,
        step: str,
        operation: Callable[[], None],
        run: RetrospectiveRun,
        state: RetrospectiveState,
        access: AnnualStateAccess,
    ) -> None:
        if step in run["completed"]:
            self.effects.echo(f"Already completed: {step}")
            return
        self.effects.cancel()
        self.effects.echo(f"Running: {step}")
        operation()
        run["completed"].append(step)
        access.save(state)
