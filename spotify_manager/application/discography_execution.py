"""Execute confirmed artist removals, per-artist audits and one final checkpoint."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.discography_values import DiscographyRunSummary
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import ArtistSelection
from spotify_manager.domain.discography_values import DiscographyPlan
from spotify_manager.domain.discography_values import QueueName


class DiscographyStateAccess(Protocol):
    """Preserve complete caller-owned priority state at the final checkpoint."""

    def load(self) -> dict[str, object]:
        """Read complete accepted priority.

        Returns:
            Original complete state, including unknown fields.
        """
        ...

    def save(self, state: dict[str, object], /) -> object:
        """Accept original complete final priority.

        Args:
            state: Original loaded state with its next queue changed.

        Returns:
            Original storage acknowledgment, ignored by the runner.
        """
        ...


@dataclass(frozen=True)
class DiscographyEffects:
    """Bind original removal, audit, priority and progress boundaries.

    Args:
        remove: Original retried SDK batch acceptance.
        audit: Original successful artist audit acceptance.
        state: Original final state resolution.
        progress: Original optional progress delivery.
    """

    remove: Callable[[ArtistSelection, ArtistMarkers, list[str]], None]
    audit: Callable[[ArtistSelection, QueueName], None]
    state: Callable[[], DiscographyStateAccess]
    progress: Callable[[str], None]


@dataclass(frozen=True)
class DiscographyExecution:
    """Preserve accepted-effect order without adding restart or mutation semantics.

    Args:
        effects: Original complete accepted-effect boundaries.
        batch_size: Original maximum unique removal batch size.
    """

    effects: DiscographyEffects
    batch_size: int = 100

    def run(self, plan: DiscographyPlan) -> DiscographyRunSummary:
        """Remove every artist, audit each one, then checkpoint priority once.

        Args:
            plan: Original confirmed complete batch.

        Returns:
            Original completed artist and successful unique marker counts.
        """
        removed = 0
        for selection in plan.artists:
            self.effects.progress(f"Removing {selection.name} from discography queues")
            removed += self._remove(selection)
            self.effects.audit(selection, plan.next_queue)
        state_access = self.effects.state()
        state = state_access.load()
        state["next_queue"] = plan.next_queue
        state_access.save(state)
        return DiscographyRunSummary(len(plan.artists), removed, plan.next_queue)

    def _remove(self, selection: ArtistSelection) -> int:
        removed = 0
        for group in selection.markers:
            uris = list(dict.fromkeys(group.uris))
            removed += self._remove_group(selection, group, uris)
        return removed

    def _remove_group(
        self,
        selection: ArtistSelection,
        group: ArtistMarkers,
        uris: list[str],
    ) -> int:
        removed = 0
        for start in range(0, len(uris), self.batch_size):
            batch = uris[start : start + self.batch_size]
            self.effects.remove(selection, group, batch)
            removed += len(batch)
        return removed
