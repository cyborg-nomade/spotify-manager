"""Caller-owned Queue state observations and accepted checkpoint boundaries."""

from typing import Protocol


class QueueStateAccess(Protocol):
    """Read original mutable Queue state and accept complete checkpoints."""

    def load(self) -> dict[str, object]:
        """Read the original complete Queue state.

        Returns:
            Original caller-owned mutable state document.
        """

    def save(self, state: dict[str, object], /) -> object:
        """Accept an original complete checkpoint without interpreting acknowledgment.

        Args:
            state: Original complete mutable state.

        Returns:
            Original storage acknowledgment, ignored by the workflows.
        """
