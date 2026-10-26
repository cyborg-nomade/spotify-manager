"""Replay original removal batches, completion failures and confirmed-plan retries."""

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.discography_execution import DiscographyExecution
from spotify_manager.application.discography_execution import DiscographyStateAccess
from spotify_manager.application.discography_values import DiscographyRunSummary
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import ArtistSelection
from spotify_manager.domain.discography_values import QueueName
from tests.support.discography_apply import ApplyEffects
from tests.support.discography_apply import apply_outcome
from tests.support.discography_apply import plan
from tests.support.discography_run import cases


LABELS = {
    "newfoundland": "Newfoundland",
    "memory_lane": "Memory Lane",
    "requeue": "The Requeue",
    "queue_3": "The Queue 3",
}


def _remove(
    edge: ApplyEffects,
    selection: ArtistSelection,
    group: ArtistMarkers,
    batch: list[str],
) -> None:
    operation = partial(
        edge._delete,
        f"playlists/{group.playlist_id}/items",
        {"items": [{"uri": uri} for uri in batch]},
    )
    edge.retry(operation, f"removing {selection.name} from {LABELS[group.queue]}")


def _state(edge: ApplyEffects) -> DiscographyStateAccess:
    edge.state(Path("state"), None)
    return edge


def _audit(
    edge: ApplyEffects, selection: ArtistSelection, next_queue: QueueName
) -> None:
    edge.audit(selection, next_queue, Path("audit"))


@dataclass(frozen=True)
class ObservedWrites:
    """Expose the original accepted effects as named adapter methods.

    Args:
        edge: Original observed writes, authority and failures.
    """

    edge: ApplyEffects

    def remove(
        self, selection: ArtistSelection, group: ArtistMarkers, batch: list[str]
    ) -> None:
        """Accept the original removal and its retry observation.

        Args:
            selection: Confirmed artist.
            group: Original source markers.
            batch: Original unique removal URIs.
        """
        _remove(self.edge, selection, group, batch)

    def audit(self, selection: ArtistSelection, next_queue: QueueName) -> None:
        """Accept the original completion audit.

        Args:
            selection: Confirmed artist and exact releases.
            next_queue: Original next-run priority.
        """
        _audit(self.edge, selection, next_queue)

    def state(self) -> DiscographyStateAccess:
        """Resolve the original priority authority after accepted removals."""
        return _state(self.edge)

    def progress(self, message: str) -> None:
        """Deliver the original per-artist notification.

        Args:
            message: Original stage text.
        """
        self.edge.progress(message)


def _run(edge: ApplyEffects, empty: bool) -> DiscographyRunSummary:
    effects = ObservedWrites(edge)
    return DiscographyExecution(effects).run(plan(empty))


@pytest.mark.parametrize("case", cases("discography_apply.json"))
def test_discography_apply_retains_original_accepted_effects(
    case: dict[str, object],
) -> None:
    """Compare complete outcomes, accepted effects and replayed confirmed plans.

    Args:
        case: Original immutable success or failure/replay input.
    """
    failure = cast(str | None, case["failure"])
    empty, resume = bool(case["empty"]), bool(case["resume"])
    assert apply_outcome(failure, empty, resume, _run) == case["outcome"]
    assert apply_outcome(failure, empty, resume) == case["outcome"]
