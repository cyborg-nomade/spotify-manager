"""Original annual clock, destination, state, discovery and cancellation boundaries."""

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


class AnnualEffects(Protocol):
    """Observe annual preflight authority and deliver real user interactions."""

    def clock(self) -> datetime:
        """Observe the effective calendar time.

        Returns:
            Original effective Berlin timestamp.
        """

    def destinations(self) -> dict[str, str]:
        """Read and validate the configured destinations.

        Returns:
            Ordered destination identities.
        """

    def state(self) -> AnnualStateAccess:
        """Resolve durable annual authority after destination validation.

        Returns:
            Original complete namespace access.
        """

    def owned(self) -> tuple[OwnedPlaylist, ...]:
        """Read current owned playlists.

        Returns:
            Original complete current source facts.
        """

    def cancel(self) -> None:
        """Raise the original cancellation error when requested."""

    def echo(self, message: str) -> None:
        """Present the original stage text.

        Args:
            message: Original visible message.
        """
