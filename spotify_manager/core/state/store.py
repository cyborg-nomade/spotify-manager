"""Storage port for the single shared state document."""

from typing import Protocol

from spotify_manager.core.state.models import StateSnapshot


class StateStore(Protocol):
    """Read and compare-and-swap one versioned JSON document."""

    def read(self) -> StateSnapshot:
        """Return the current state and its immutable store revision."""

    def write(
        self,
        document: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> StateSnapshot:
        """Replace state only when the store still has the expected revision."""
