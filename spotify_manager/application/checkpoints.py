"""Named checkpoint ownership for workflows sharing mutable preferences."""

from dataclasses import dataclass
from typing import Protocol


class StateWriter(Protocol):
    """Persist a complete namespace through its existing store."""

    def save(self, state: dict[str, object], /) -> object:
        """Accept one namespace checkpoint.

        Args:
            state: Complete current namespace.

        Returns:
            Original storage acknowledgment, ignored by the caller.
        """


class Checkpoint(Protocol):
    """Checkpoint the current invocation without exposing a forwarding callback."""

    def save(self) -> None:
        """Persist the invocation's current state at an accepted boundary."""


@dataclass(frozen=True)
class NamespaceCheckpoint:
    """Own the namespace and preview rule used by preference checkpoints.

    Args:
        store: Existing persistence boundary.
        state: Shared mutable namespace.
        dry_run: Whether durable writes are suppressed.
    """

    store: StateWriter
    state: dict[str, object]
    dry_run: bool

    def save(self) -> None:
        """Persist accepted preferences only during real execution."""
        if not self.dry_run:
            self.store.save(self.state)


class ModelCheckpoint[T](Protocol):
    """Persist a complete typed progress model."""

    def save(self, state: T) -> None:
        """Accept current progress.

        Args:
            state: Complete current model.
        """
        ...


class NoCheckpoint:
    """Keep standalone preview planning detached from persistent preferences."""

    def save(self) -> None:
        """Accept a detached planning checkpoint without storing state."""
