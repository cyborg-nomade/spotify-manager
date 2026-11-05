"""Back up and migrate existing New Kids artists at a fresh-run boundary."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.new_kids_migration_selection import (
    NewKidsMigrationSelection,
)
from spotify_manager.application.new_kids_plan_records import plan_record
from spotify_manager.application.new_kids_plan_records import saved_plan
from spotify_manager.application.new_kids_state import artist_progress
from spotify_manager.application.new_kids_state import logical_artist
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.application.ports.runtime import Clock
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.state import AsyncRoutineState
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.new_kids_plans import ReleasePlan


@dataclass
class NewKidsPlanMigration:
    """Save each accepted plan independently without mutating playlist markers.

    Args:
        selection: Named current-edition and ordered-plan selection stage.
        state_access: Existing namespace checkpoint authority.
        state: Live namespace or a detached preview clone.
        clock: Existing invocation clock.
        presentation: Existing output boundary.
        dry_run: Suppress backup and progress writes.
        skipped: Invocation-local logical artists deferred by the operator.
    """

    selection: NewKidsMigrationSelection
    state_access: AsyncRoutineState
    state: dict[str, object]
    clock: Clock
    presentation: Messages
    dry_run: bool
    skipped: set[str] = field(default_factory=set, init=False)

    async def run(self, current: list[PlaylistTrack]) -> None:
        """Migrate each unplanned live artist once, retaining accepted earlier choices.

        Args:
            current: Complete live New Kids markers before prefill or advancement.

        Raises:
            NewKidsStateError: Artist progress or a saved plan is invalid.
            ReleasePlanStoppedError: The operator quits; earlier plans remain saved.
        """
        seen: set[str] = set()
        for source in current:
            artist_id, name = logical_artist(self.state, source)
            if artist_id in seen:
                continue
            seen.add(artist_id)
            if self._planned(artist_id):
                continue
            plan = await self.selection.run(source, artist_id, name)
            if plan is None:
                self.skipped.add(artist_id)
                continue
            await self._accept(source, artist_id, name, plan)

    def _planned(self, artist_id: str) -> bool:
        artists = self.state.get("artists")
        if not isinstance(artists, dict):
            raise NewKidsStateError("New Kids artist progress is invalid.")
        progress = artists.get(artist_id)
        return isinstance(progress, dict) and saved_plan(progress) is not None

    async def _backup(self) -> None:
        if self.dry_run:
            return
        backup = self.state.get("release_plan_migration_backup")
        if backup is not None:
            if (
                not isinstance(backup, dict)
                or backup.get("version") != 1
                or not isinstance(backup.get("namespace"), dict)
            ):
                raise NewKidsStateError(
                    "The migration backup is invalid; preserve it before continuing."
                )
            return
        self.state["release_plan_migration_backup"] = {
            "version": 1,
            "created_at": self.clock.now().isoformat(),
            "namespace": deepcopy(self.state),
        }
        await self.state_access.save(self.state)

    async def _accept(
        self, source: PlaylistTrack, artist_id: str, name: str, plan: ReleasePlan
    ) -> None:
        await self._backup()
        progress = artist_progress(self.state, source, artist_id, name, self.clock)
        progress["release_plan"] = plan_record(plan)
        progress["current_release_id"] = plan.releases[plan.position].spotify_id
        progress["release_plan_marker"] = {
            "track_id": source.spotify_id,
            "release_id": progress["current_release_id"],
        }
        if not self.dry_run:
            await self.state_access.save(self.state)
        self.presentation.echo(
            f"{'Would migrate' if self.dry_run else 'Migrated'} {name}; "
            f"continuing at {source.name}."
        )

    def review_markers(self, current: list[PlaylistTrack]) -> list[PlaylistTrack]:
        """Exclude deferred artists from both planned and legacy review this run.

        Args:
            current: Post-prefill projected markers.

        Returns:
            Existing review order without invocation-local migration skips.
        """
        result = []
        for marker in current:
            if logical_artist(self.state, marker)[0] not in self.skipped:
                result.append(marker)
        return result

    def deferred(self) -> None:
        """Explain the preserved safe boundary when resuming a saved review."""
        self.presentation.echo(
            "Resuming the saved New Kids run; existing-artist plans "
            "will be requested on the next fresh run."
        )
