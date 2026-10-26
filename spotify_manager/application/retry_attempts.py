"""Retry scope iteration without capturing or invoking a supplied function."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Protocol
from typing import Self

from spotify_manager.application.ports.runtime import Cancellation


class AttemptPolicy(Protocol):
    """Own the original entry, accepted-result and failure behavior of a retry."""

    def start(self) -> None:
        """Observe entry before the first request attempt."""
        ...

    def accepted(self) -> None:
        """Observe acceptance after the operation completes successfully."""
        ...

    def failed(self, error: BaseException) -> bool:
        """Classify a failed attempt and perform its existing wait or translation.

        Args:
            error: Original operation failure.

        Returns:
            Whether to suppress this failure and repeat the operation.
        """
        ...


@dataclass
class RetryAttempts(Iterator[AbstractContextManager[None]]):
    """Iterate policy-owned attempt scopes without hiding the operation.

    Args:
        policy: Existing retry, cancellation and notification decisions.
        started: Whether the original entry observation has happened.
        complete: Whether an attempt has completed successfully.
    """

    policy: AttemptPolicy
    started: bool = False
    complete: bool = False

    def __iter__(self) -> Self:
        """Continue this retry boundary.

        Returns:
            This invocation's iterator.
        """
        return self

    def __next__(self) -> AbstractContextManager[None]:
        """Begin another attempt unless an earlier attempt completed.

        Returns:
            Scope for the next direct operation.

        Raises:
            StopIteration: An earlier attempt completed successfully.
        """
        if self.complete:
            raise StopIteration
        if not self.started:
            self.policy.start()
            self.started = True
        return RetryAttempt(self)


@dataclass(frozen=True)
class RetryAttempt(AbstractContextManager[None]):
    """Report one direct operation's outcome to its existing retry policy.

    Args:
        attempts: Retry boundary owning this attempt.
    """

    attempts: RetryAttempts

    def __enter__(self) -> None:
        """Begin the operation directly inside the caller's with statement."""

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Accept the result or preserve the original failure decision.

        Args:
            kind: Original failure type.
            error: Original raised failure.
            traceback: Original operation traceback.

        Returns:
            Whether a retryable failure was handled by the retry policy.
        """
        if error is not None:
            return self.attempts.policy.failed(error)
        self.attempts.complete = True
        self.attempts.policy.accepted()
        return False


@dataclass
class CheckedAttempts(Iterator[AbstractContextManager[None]]):
    """Keep the original post-success cancellation boundary around attempts.

    Args:
        scopes: Original request attempt iterator.
        cancellation: Cancellation owner checked after acceptance.
    """

    scopes: Iterator[AbstractContextManager[None]]
    cancellation: Cancellation

    def __iter__(self) -> Self:
        """Return this invocation's scopes.

        Returns:
            This retry iterator.
        """
        return self

    def __next__(self) -> AbstractContextManager[None]:
        """Wrap the next original scope without executing its operation.

        Returns:
            Scope retaining the original acceptance check.

        Raises:
            StopIteration: The original retry boundary is complete.
        """
        return CheckedAttempt(next(self.scopes), self.cancellation)


@dataclass(frozen=True)
class CheckedAttempt(AbstractContextManager[None]):
    """Check cancellation after a successful scope, including a return statement.

    Args:
        scope: Original request attempt.
        cancellation: Original cancellation owner.
    """

    scope: AbstractContextManager[None]
    cancellation: Cancellation

    def __enter__(self) -> None:
        """Enter the original request scope."""
        self.scope.__enter__()

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Keep failure handling before the original successful cancellation check.

        Args:
            kind: Original failure type.
            error: Original failure.
            traceback: Original traceback.

        Returns:
            The original scope's failure handling decision.
        """
        handled = self.scope.__exit__(kind, error, traceback)
        if error is None:
            self.cancellation.check()
        return handled
