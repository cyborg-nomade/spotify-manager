"""Bound unavoidable blocking work to the owning async invocation."""

import asyncio
from contextvars import ContextVar
from contextvars import Token
from dataclasses import dataclass
from dataclasses import field
from types import TracebackType


_CAPACITY: ContextVar[asyncio.Semaphore | None] = ContextVar(
    "spotify_manager_blocking_capacity", default=None
)


def blocking_capacity() -> asyncio.Semaphore:
    """Read the invocation's worker capacity, creating it at an outer edge.

    Returns:
        A semaphore inherited by this invocation's child tasks.
    """
    capacity = _CAPACITY.get()
    if capacity is None:
        capacity = asyncio.Semaphore(4)
        _CAPACITY.set(capacity)
    return capacity


@dataclass
class BlockingBinding:
    """Share one owner's worker bound with its request and child task contexts.

    Args:
        capacity: Loop-owned bound for remaining blocking SDK and file operations.
    """

    capacity: asyncio.Semaphore
    _token: Token[asyncio.Semaphore | None] | None = field(default=None, init=False)

    def __enter__(self) -> None:
        """Bind worker ownership before creating child tasks."""
        self._token = _CAPACITY.set(self.capacity)

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the outer worker scope.

        Args:
            kind: Original context failure type.
            error: Original failure.
            traceback: Original failure traceback.
        """
        if self._token is not None:
            _CAPACITY.reset(self._token)
            self._token = None
