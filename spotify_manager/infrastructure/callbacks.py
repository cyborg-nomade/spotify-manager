"""Concrete synchronous invocation when an interface supplies no retry policy."""

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class LegacyCheckpoint:
    """Adapt an external legacy checkpoint hook at its compatibility entry.

    Args:
        callback: Existing caller-supplied persistence hook.
    """

    callback: Callable[[], None]

    def save(self) -> None:
        """Invoke the original persistence hook exactly once."""
        self.callback()


def call_direct(operation: Callable[[], object], _description: str) -> object:
    """Execute the supplied operation once.

    Args:
        operation: Caller-owned read or effect.
        _description: Diagnostic label accepted by the common retry protocol.

    Returns:
        The operation's original result.

    Raises:
        RuntimeError: The supplied operation fails.
    """
    return operation()
