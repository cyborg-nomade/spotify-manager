"""Check backlog counts, preserve overrides and admit new routine invocations."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.ports.runtime import Clock
from spotify_manager.domain.flush_mode import BLOCKED_COMMANDS
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.domain.flush_mode import FlushState
from spotify_manager.domain.flush_mode import QueueCounts


class FlushModeBlockedError(RuntimeError):
    """A new invocation is blocked by effective Flush Mode."""


class FlushModeCheckError(RuntimeError):
    """Complete live queue counts could not be observed."""


class FlushModeStore(Protocol):
    """Read and update typed state while merging concurrent control changes."""

    async def load(self) -> FlushState:
        """Read control, automatic decision and retained observations.

        Returns:
            Validated state, defaulting to unobserved Automatic when absent.
        """
        ...

    async def control(self, value: FlushControl) -> FlushState:
        """Persist the operator selection without changing observations.

        Args:
            value: Persistent control selection.

        Returns:
            Committed state preserving the latest observations.
        """
        ...

    async def observed(
        self, counts: QueueCounts, started: str, completed: str
    ) -> FlushState:
        """Merge observations without overwriting a concurrent manual override.

        Args:
            counts: Complete successful observations.
            started: UTC check start, used to reject older results.
            completed: UTC successful completion.

        Returns:
            Latest committed state, or a newer check already stored.
        """
        ...

    async def failed(self, started: str, detail: str) -> FlushState:
        """Record a failure while retaining the prior decision and counts.

        Args:
            started: UTC check start, used to reject older failures.
            detail: Operator-facing failure reason.

        Returns:
            Latest state with a failure notice or newer observations.
        """
        ...


class QueueCountReader(Protocol):
    """Read both live playlists without running any listening routine."""

    async def read(self) -> QueueCounts:
        """Observe both counts, failing if either cannot be validated.

        Returns:
            Complete counts, including unavailable playlist entries.

        Raises:
            FlushModeCheckError: Counts are unavailable or invalid.
        """
        ...


def require_routine_start(command: str, state: FlushState) -> None:
    """Reject a new start or resume before any routine effects.

    Args:
        command: Canonical command identity at its external start boundary.
        state: Validated shared policy observed at the start boundary.

    Raises:
        FlushModeBlockedError: Effective Flush Mode blocks this command.
        StateError: The control decision cannot be read safely.
    """
    if command in BLOCKED_COMMANDS and state.active:
        raise FlushModeBlockedError(
            "Flush Mode is active. This routine is blocked until it is deactivated."
        )


@dataclass(frozen=True)
class NewWineMode:
    """Retain the requested setting separately from mandatory recovery policy.

    Args:
        no_discovery: Effective initial setting for a fresh run.
        forced: Whether current Flush Mode must override a saved false setting.
    """

    no_discovery: bool
    forced: bool


def new_wine_no_discovery(requested: bool, state: FlushState) -> NewWineMode:
    """Resolve one New Wine invocation's initial recovery preference.

    Args:
        requested: Operator's ordinary No Discovery setting.
        state: Shared policy state read once at admission.

    Returns:
        Whether recovery eligibility is initially required for this invocation.
    """
    return NewWineMode(state.active or requested, state.active)


async def check_flush_mode(
    store: FlushModeStore, counts: QueueCountReader, clock: Clock
) -> FlushState:
    """Refresh automatic observations without undoing a persistent override.

    Args:
        store: Conflict-aware state owner.
        counts: Live complete queue observations.
        clock: UTC clock for start ordering and successful completion.

    Returns:
        Updated state, retaining the previous decision on observation failure.

    Raises:
        StateError: The decision or failure cannot be persisted safely.
    """
    started = clock.now().isoformat()
    try:
        observed = await counts.read()
    except FlushModeCheckError as exc:
        return await store.failed(started, str(exc))
    return await store.observed(observed, started, clock.now().isoformat())
