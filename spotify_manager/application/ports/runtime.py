"""Named runtime resources used by routines without function-shaped dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import TYPE_CHECKING
from typing import Protocol


if TYPE_CHECKING:
    from spotify_manager.application.historical_values import RandomIndexSet
    from spotify_manager.domain.library_analysis_values import ResourceName


class Messages(Protocol):
    """Present messages at the application-selected observation boundary."""

    def echo(self, message: str, /) -> None:
        """Present one original message.

        Args:
            message: Complete text, retaining its existing formatting.
        """
        ...


class ReviewProgress(Protocol):
    """Report review progress and observe cancellation at the same boundary."""

    def progress(self, completed: int, total: int, detail: str, /) -> None:
        """Accept the current review position.

        Args:
            completed: Number of completed entries.
            total: Original expected entry count.
            detail: Current operation description.
        """
        ...


class Retry(Protocol):
    """Provide retry scopes while keeping the operation visible at its call site."""

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Open the original retry boundary for a directly named operation.

        Args:
            description: Existing visible operation label.

        Returns:
            Attempt scopes; retryable failures advance to the next scope.
        """
        ...


class NoRetry:
    """Execute a direct operation once, propagating its original failure."""

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Provide one scope without changing the original exception.

        Args:
            description: Diagnostic label accepted by the retry interface.

        Returns:
            One direct execution scope.
        """
        return iter((nullcontext(),))


NO_RETRY = NoRetry()


class CountProgress(Protocol):
    """Report progress for an item-counted review."""

    def progress(self, completed: int, total: int, /) -> None:
        """Accept the current item counts.

        Args:
            completed: Completed entries.
            total: Original expected entries.
        """
        ...


class AnalysisProgress(Protocol):
    """Report one resource in a resumable library analysis."""

    def progress(
        self, resource: ResourceName, completed: int, total: int | None, detail: str, /
    ) -> None:
        """Accept resource progress and observe cancellation.

        Args:
            resource: Active library resource.
            completed: Completed entries.
            total: Expected entries, when known.
            detail: Current operation description.
        """
        ...


@dataclass(frozen=True)
class OptionalMessages:
    """Present notifications only when the invocation supplies an output.

    Args:
        output: Caller-owned message resource or no observer.
    """

    output: Messages | None

    def echo(self, message: str, /) -> None:
        """Present an original optional notification.

        Args:
            message: Complete original text.
        """
        if self.output is not None:
            self.output.echo(message)


@dataclass(frozen=True)
class OptionalReviewProgress:
    """Report review progress only when the invocation supplies an observer.

    Args:
        observer: Original optional review observer.
    """

    observer: ReviewProgress | None

    def progress(self, completed: int, total: int, detail: str, /) -> None:
        """Report the original counts and description.

        Args:
            completed: Completed entries.
            total: Expected entries.
            detail: Original operation description.
        """
        if self.observer is not None:
            self.observer.progress(completed, total, detail)


@dataclass(frozen=True)
class ReviewProgressMessages:
    """Translate history messages into the original review progress notification.

    Args:
        observer: Review observer receiving zero-count history notifications.
    """

    observer: ReviewProgress | None

    def echo(self, message: str, /) -> None:
        """Present the original history message before review counts are known.

        Args:
            message: Original history operation description.
        """
        if self.observer is not None:
            self.observer.progress(0, 0, message)


class Clock(Protocol):
    """Own the now observation without an injected function."""

    def now(self) -> datetime:
        """Observe the original runtime boundary.

        Returns:
            Original observed value.
        """
        ...


class DateClock(Protocol):
    """Own the today observation without an injected function."""

    def today(self) -> date:
        """Observe the original runtime boundary.

        Returns:
            Original observed value.
        """
        ...


class TimestampClock(Protocol):
    """Own the timestamp observation without an injected function."""

    def timestamp(self) -> str:
        """Observe the original runtime boundary.

        Returns:
            Original observed value.
        """
        ...


class YearClock(Protocol):
    """Own the year observation without an injected function."""

    def year(self) -> int:
        """Observe the original runtime boundary.

        Returns:
            Original observed value.
        """
        ...


class MonotonicClock(Protocol):
    """Own the monotonic observation without an injected function."""

    def monotonic(self) -> float:
        """Observe the original runtime boundary.

        Returns:
            Original observed value.
        """
        ...


class CancellationState(Protocol):
    """Own the cancelled observation without an injected function."""

    def is_set(self) -> bool:
        """Observe the original runtime boundary.

        Returns:
            Original observed value.
        """
        ...


class Cancellation(Protocol):
    """Own the check observation without an injected function."""

    def check(self) -> None:
        """Observe the original runtime boundary."""
        ...


class Wait(Protocol):
    """Own the sleep observation without an injected function."""

    def sleep(self, seconds: float) -> None:
        """Observe the original runtime boundary.

        Args:
            seconds: Original wait duration.
        """
        ...


class RandomIndexes(Protocol):
    """Read an external random index set."""

    def sample(self, population: int, count: int) -> RandomIndexSet:
        """Read indexes using the original external random source.

        Args:
            population: Eligible population size.
            count: Requested indexes.

        Returns:
            Original random index response.
        """
        ...
