"""Freeze original Discography removal, audit and final checkpoint ordering."""

import json
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.core.state.compat import RoutineState
from spotify_manager.core.state.service import StateService
from spotify_manager.routines import discography as legacy
from tests.support.discography_run import release


FAILURES = (
    "progress:1",
    "progress:2",
    "retry:1",
    "retry:2",
    "retry:3",
    "delete:1",
    "delete:2",
    "accepted-delete:1",
    "audit:1",
    "audit:2",
    "state-access",
    "state-load",
    "state-save",
    "accepted-state-save",
)


def plan(empty: bool = False) -> legacy.DiscographyPlan:
    """Build original duplicate, multi-batch and multiple-artist markers.

    Args:
        empty: Whether the original plan contains no selections.

    Returns:
        Complete original confirmed plan.
    """
    if empty:
        return legacy.DiscographyPlan("requeue", "requeue", (), 0, 0)
    uris = tuple(f"uri-{index}" for index in range(102)) + ("uri-0",)
    artists = (
        legacy.ArtistSelection(
            "a",
            "Alpha",
            "newfoundland",
            (release("a"),),
            (
                legacy.ArtistMarkers("newfoundland", "nf", uris),
                legacy.ArtistMarkers("queue_3", "extra", ("extra", "extra")),
            ),
        ),
        legacy.ArtistSelection(
            "b",
            "Beta",
            "requeue",
            (release("b"),),
            (legacy.ArtistMarkers("requeue", "rq", ("last",)),),
        ),
    )
    return legacy.DiscographyPlan("newfoundland", "requeue", artists, 2, 8)


@dataclass
class ApplyEffects:
    """Observe original accepted removals and durable priority across retries.

    Args:
        failure: Original accepted boundary that fails.
        trace: Complete ordered effects.
        removed: Accepted external removal identities.
        priority: Original accepted durable state.
    """

    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    priority: str = "newfoundland"

    def record(self, action: str, *details: object) -> None:
        """Observe an original boundary and configured failure.

        Args:
            action: Original boundary identity.
            details: Complete observed arguments.

        Raises:
            RuntimeError: The configured original stage fails.
        """
        self.trace.append([action, *details])
        self.fail(action)

    def fail(self, action: str) -> None:
        """Fail before or after acceptance at the original configured boundary.

        Args:
            action: Original failure boundary.

        Raises:
            RuntimeError: The configured boundary fails.
        """
        observed = action.removeprefix("accepted-")
        count = sum(row[0] == observed for row in self.trace)
        if self.failure in {action, f"{action}:{count}"}:
            raise RuntimeError(f"{self.failure} failed")

    def _delete(self, path: str, payload: dict[str, object]) -> None:
        """Accept original SDK removal batches.

        Args:
            path: Original mutation path.
            payload: Original exact mutation body.
        """
        self.record("delete", path, payload)
        items = cast(list[dict[str, str]], payload["items"])
        self.removed.extend(item["uri"] for item in items)
        self.fail("accepted-delete")

    def retry(self, operation: Callable[[], object], description: str) -> object:
        """Observe original retry wrappers.

        Args:
            operation: Original deferred mutation.
            description: Original retry label.

        Returns:
            Original result.
        """
        self.record("retry", description)
        return operation()

    def progress(self, message: str) -> None:
        """Observe original progress text.

        Args:
            message: Original visible stage.
        """
        self.record("progress", message)

    def audit(
        self,
        selection: legacy.ArtistSelection,
        next_queue: legacy.QueueName,
        path: Path,
    ) -> None:
        """Accept original artist completion audit.

        Args:
            selection: Original fully removed artist.
            next_queue: Original final planned priority.
            path: Original audit destination.
        """
        self.record("audit", asdict(selection), next_queue, str(path))

    def state(self, path: Path, service: StateService | None) -> RoutineState:
        """Resolve original final durable state.

        Args:
            path: Original priority file.
            service: Original optional shared service.

        Returns:
            Original in-memory access.
        """
        self.record("state-access", str(path), service is None)
        return cast(RoutineState, self)

    def load(self) -> dict[str, object]:
        """Load original durable priority after every artist audit.

        Returns:
            Original accepted complete state with unknown fields.
        """
        self.record("state-load")
        return {"version": 1, "next_queue": self.priority, "retained": "value"}

    def save(self, state: dict[str, object]) -> None:
        """Accept original single final checkpoint.

        Args:
            state: Original complete mutated state.
        """
        self.record("state-save", dict(state))
        self.priority = cast(str, state["next_queue"])
        self.fail("accepted-state-save")


def original_apply(edge: ApplyEffects, empty: bool) -> legacy.DiscographyRunSummary:
    """Run the original public apply coordinator.

    Args:
        edge: Original ordered effect observations.
        empty: Original empty-plan behavior.

    Returns:
        Original complete removal summary.
    """
    with ExitStack() as stack:
        stack.enter_context(patch.object(legacy, "_append_log", edge.audit))
        stack.enter_context(patch.object(legacy, "_state_access", edge.state))
        return legacy.apply_discography_plan(
            cast(Spotify, edge),
            plan(empty),
            retry_call=edge.retry,
            progress_callback=edge.progress,
            state_path=Path("state"),
            log_path=Path("audit"),
        )


def apply_outcome(
    failure: str | None,
    empty: bool,
    resume: bool,
    run: Callable[[ApplyEffects, bool], legacy.DiscographyRunSummary] = original_apply,
) -> object:
    """Capture original accepted effects and optional replay of the confirmed plan.

    Args:
        failure: Original configured boundary failure.
        empty: Original empty plan.
        resume: Whether to rerun the same confirmed plan after failure.
        run: Original or independently injected apply coordinator.

    Returns:
        Complete original result, error, accepted effects and ordered trace.
    """
    edge = ApplyEffects(failure)
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = asdict(run(edge, empty))
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    if resume:
        edge.failure = None
        outcome["resumed"] = asdict(run(edge, empty))
    outcome.update(trace=edge.trace, removed=edge.removed, priority=edge.priority)
    return json.loads(json.dumps(outcome))
