"""Decide backlog hysteresis and routine admission without observing services."""

from dataclasses import dataclass
from dataclasses import replace
from typing import Literal


type FlushControl = Literal["automatic", "on", "off"]
BLOCKED_COMMANDS = frozenset(
    {
        "found_art",
        "genre_reveal",
        "fill_queue_from_lastfm",
        "flush_queue",
        "flush_queue_2",
        "flush_queue_3",
        "import_queue_3_previous_year",
        "fill_sauvignon_from_lastfm",
    }
)


@dataclass(frozen=True)
class QueueCounts:
    """Contain complete live counts for both backlog playlists.

    Args:
        queue: Number of items in The Queue, including unavailable markers.
        queue_2: Number of items in Queue 2, including unavailable markers.
    """

    queue: int
    queue_2: int


@dataclass(frozen=True)
class FlushState:
    """Keep the automatic decision separate from the persistent operator override.

    Args:
        control: Automatic selection, forced on, or forced off.
        automatic_active: Latest successful hysteresis decision.
        counts: Latest complete successful observations, if any.
        checked_at: UTC completion timestamp of the last successful check.
        attempted_at: UTC start timestamp ordering successful and failed checks.
        error: Latest count-check failure, without discarding previous observations.
    """

    control: FlushControl = "automatic"
    automatic_active: bool = False
    counts: QueueCounts | None = None
    checked_at: str | None = None
    attempted_at: str | None = None
    error: str | None = None

    @property
    def active(self) -> bool:
        """Return the effective mode under the persistent control selection.

        Returns:
            Forced selection, or the automatic decision.
        """
        if self.control == "automatic":
            return self.automatic_active
        return self.control == "on"


def automatic_flush(previous: bool, counts: QueueCounts) -> bool:
    """Apply activation thresholds and separate exit thresholds.

    Args:
        previous: Previous automatic decision, independent of manual overrides.
        counts: Complete live observations for both queues.

    Returns:
        True at either activation threshold, retained until both exit thresholds.
    """
    if counts.queue >= 2400 or counts.queue_2 >= 1200:
        return True
    if counts.queue <= 1200 and counts.queue_2 <= 900:
        return False
    return previous


def flush_reason(state: FlushState) -> str:
    """Explain the effective mode and the retained automatic decision.

    Args:
        state: Latest persisted control and successful observations.

    Returns:
        Operator-facing explanation, including unobserved and hysteresis cases.
    """
    if state.control != "automatic":
        return "Manual override: Flush Mode forced " + state.control + "."
    if state.counts is None:
        return "No successful count check yet."
    if not state.automatic_active:
        return "Automatic mode is normal; activation thresholds are not reached."
    if state.counts.queue >= 2400:
        return "The Queue has reached 2,400 tracks."
    if state.counts.queue_2 >= 1200:
        return "Queue 2 has reached 1,200 tracks."
    return "Waiting for The Queue ≤ 1,200 and Queue 2 ≤ 900."


def discovery_fallback(no_discovery: bool, after: int, target: int) -> bool:
    """Permit normal discovery only for capacity recovery could not fill.

    Args:
        no_discovery: Whether the completed recovery pass restricted eligibility.
        after: Observed or projected destination size after that pass.
        target: Maximum destination size.

    Returns:
        Whether a second, unrestricted pass may fill remaining slots.
    """
    return no_discovery and after < target


@dataclass(frozen=True)
class FlushChange:
    """Describe one field-preserving state change without execution callbacks.

    Args:
        control: Operator override, when changing only control.
        counts: Complete successful observations, or none for a failed check.
        started: UTC check start ordering results from concurrent checks.
        completed: Successful completion timestamp.
        error: Count-check failure detail.
    """

    control: FlushControl | None = None
    counts: QueueCounts | None = None
    started: str | None = None
    completed: str | None = None
    error: str | None = None

    def apply(self, state: FlushState) -> FlushState:
        """Merge only owned fields into the newest validated state.

        Args:
            state: Latest stored control and observations.

        Returns:
            Updated state, or unchanged state when a newer check already won.
        """
        if self.control is not None:
            return replace(state, control=self.control)
        assert self.started is not None
        if state.attempted_at is not None and self.started < state.attempted_at:
            return state
        if self.counts is None:
            return replace(state, attempted_at=self.started, error=self.error)
        return replace(
            state,
            counts=self.counts,
            checked_at=self.completed,
            attempted_at=self.started,
            error=None,
            automatic_active=automatic_flush(state.automatic_active, self.counts),
        )
