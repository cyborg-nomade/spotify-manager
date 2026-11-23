"""Execute the original five annual steps with per-step accepted checkpoints."""

from dataclasses import dataclass

from spotify_manager.application.new_year_charts import AnnualCharts
from spotify_manager.application.new_year_charts import ChartKind
from spotify_manager.application.new_year_discoveries import AnnualDiscoveries
from spotify_manager.application.new_year_effects import AnnualEffects
from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_values import RetrospectivePlan
from spotify_manager.application.new_year_values import RetrospectiveRun
from spotify_manager.application.new_year_values import RetrospectiveState
from spotify_manager.domain.annual_history import accepted_uris


@dataclass(frozen=True)
class AnnualExecution:
    """Bind original charts, membership, discovery effects and completion authority.

    Args:
        effects: Original cancellation, discovery and presentation resources.
        charts: Original category chart synchronization.
        membership: Original retry-aware destination reconciliation.
        discoveries: Named annual discovery import stage.
    """

    effects: AnnualEffects
    charts: AnnualCharts
    membership: AnnualMembership
    discoveries: AnnualDiscoveries

    async def run(
        self,
        year: int,
        plan: RetrospectivePlan,
        run: RetrospectiveRun,
        state: RetrospectiveState,
        access: AnnualStateAccess,
    ) -> None:
        """Apply the five original categories with accepted per-stage checkpoints.

        Args:
            year: Completed source year.
            plan: Original complete durable plan.
            run: Mutable annual completion authority.
            state: Complete namespace retaining unknown fields.
            access: Original durable write boundary.
        """
        checkpoint = AnnualCheckpoint(self.effects, run, state, access)
        await self._chart(plan, year, "tracks", 50, "blast", checkpoint)
        await self._chart(plan, year, "albums", 20, "palace", checkpoint)
        if checkpoint.begin("top artists"):
            await self._artists(plan)
            await checkpoint.complete("top artists")
        if checkpoint.begin("Great Discoveries"):
            await self.discoveries.run(year + 1, False)
            await checkpoint.complete("Great Discoveries")
        if checkpoint.begin("Obsessions"):
            await self._append_to_blast(
                plan, plan["obsessions"], "Obsessions", checkpoint
            )
            await checkpoint.complete("Obsessions")
        run["done"] = True
        await access.save(state)
        self.effects.echo(f"The {year} retrospective is complete.")

    async def _chart(
        self,
        plan: RetrospectivePlan,
        year: int,
        kind: ChartKind,
        limit: int,
        destination: str,
        checkpoint: AnnualCheckpoint,
    ) -> None:
        step = f"top {kind}"
        if not checkpoint.begin(step):
            return
        uris = await self.charts.synchronize(plan, year, kind, limit)
        if destination == "blast":
            await self._append_to_blast(plan, uris, step, checkpoint)
        else:
            await self.membership.run(plan["destinations"][destination], uris)
        await checkpoint.complete(step)

    async def _append_to_blast(
        self,
        plan: RetrospectivePlan,
        uris: list[str],
        step: str,
        checkpoint: AnnualCheckpoint,
    ) -> None:
        playlist = plan["destinations"]["blast"]
        offsets = checkpoint.run.get("blast_offsets")
        # Older plans may have already written tracks without recording a start.
        if offsets is None:
            await self.membership.run(playlist, uris)
            return
        if not uris:
            return
        if step not in offsets:
            offsets[step] = await self.membership.playlist_length(playlist)
            await checkpoint.access.save(checkpoint.state)
        await self.membership.append_ordered(playlist, uris, offsets[step])

    async def _artists(self, plan: RetrospectivePlan) -> None:
        uris = accepted_uris(plan["artists"])
        await self.membership.run(plan["destinations"]["memory"], uris, True)


@dataclass(frozen=True)
class AnnualCheckpoint:
    """Own accepted annual stage progress without storing executable callbacks.

    Args:
        effects: Original cancellation and presentation interactions.
        run: Mutable completion authority.
        state: Complete current namespace.
        access: Original durable checkpoint boundary.
    """

    effects: AnnualEffects
    run: RetrospectiveRun
    state: RetrospectiveState
    access: AnnualStateAccess

    def begin(self, step: str) -> bool:
        """Present or skip the original checkpointed stage.

        Args:
            step: Original persisted stage name.

        Returns:
            Whether the stage must execute.
        """
        if step in self.run["completed"]:
            self.effects.echo(f"Already completed: {step}")
            return False
        self.effects.cancel()
        self.effects.echo(f"Running: {step}")
        return True

    async def complete(self, step: str) -> None:
        """Persist a stage only after all of its effects succeed.

        Args:
            step: Original accepted stage name.
        """
        self.run["completed"].append(step)
        await self.access.save(self.state)
