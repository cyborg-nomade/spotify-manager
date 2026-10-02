"""Original annual clock, destination, state, discovery and cancellation boundaries."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from spotify_manager.application.new_year_values import RetrospectiveState
from spotify_manager.domain.composers import OwnedPlaylist


class AnnualStateAccess(Protocol):
    """Read original shallow annual authority and accept complete namespace writes."""

    def load(self) -> RetrospectiveState:
        """Read original detached complete annual state.

        Returns:
            Original digit-keyed annual records, retaining unvalidated stored plans.
        """
        ...

    def save(self, state: RetrospectiveState, /) -> object:
        """Accept the original complete namespace checkpoint.

        Args:
            state: Original complete mutable annual state.

        Returns:
            Original storage acknowledgment, ignored by the runner.
        """
        ...


@dataclass(frozen=True)
class AnnualEffects:
    """Bind original preflight, persistence, discovery and presentation resources.

    Args:
        clock: Original effective Berlin clock read before all other boundaries.
        destinations: Original ordered configured destination parsing.
        state: Original caller/runtime annual state resolution.
        owned: Original owned-playlist observations excluding Queue 3.
        validate_discoveries: Original previous-year discovery source validation.
        discoveries: Original annual discovery import, retaining preview semantics.
        cancel: Original explicit cancellation boundary.
        echo: Original visible presenter.
    """

    clock: Callable[[], datetime]
    destinations: Callable[[], dict[str, str]]
    state: Callable[[], AnnualStateAccess]
    owned: Callable[[], tuple[OwnedPlaylist, ...]]
    validate_discoveries: Callable[[tuple[OwnedPlaylist, ...], int], object]
    discoveries: Callable[[int, bool], None]
    cancel: Callable[[], None]
    echo: Callable[[str], None]
