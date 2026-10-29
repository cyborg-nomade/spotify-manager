"""Verify original direct and falsey caller retry timing around cancellation checks."""

from collections.abc import Iterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass

from spotify_manager.application.new_year_retry import AnnualRetry


def _cancel(trace: list[str]) -> None:
    trace.append("cancel")


def _operation(trace: list[str]) -> int:
    trace.append("operation")
    return 11


async def test_annual_missing_caller_retry_runs_operation_between() -> None:
    """Retain original direct invocation and both cancellation boundaries."""
    trace: list[str] = []
    retry = AnnualRetry(None, TraceCancellation(trace))
    assert (await _execute(retry, trace)) == 11
    assert trace == ["cancel", "operation", "cancel"]


@dataclass
class FalseyRetry:
    """Observe original per-read truthiness and reject unexpected caller execution.

    Args:
        trace: Original ordered cancellation/operation observations.
    """

    trace: list[str]

    def __bool__(self) -> bool:
        """Observe original caller truthiness at the operation boundary.

        Returns:
            Original falsey retry authority.
        """
        self.trace.append("truthiness")
        return False

    def attempts(self, description: str) -> Iterator[AbstractAsyncContextManager[None]]:
        """Reject execution through the original falsey retry authority.

        Args:
            description: Original retry label.

        Raises:
            AssertionError: The original falsey authority must never execute.
        """
        raise AssertionError("falsey caller must not execute")


async def test_annual_falsey_retry_is_checked_only_after_first_cancellation() -> None:
    """Retain original late truthiness and direct operation semantics."""
    trace: list[str] = []
    retry = AnnualRetry(FalseyRetry(trace), TraceCancellation(trace))
    assert trace == []
    assert (await _execute(retry, trace)) == 11
    assert trace == ["cancel", "truthiness", "operation", "cancel"]


@dataclass(frozen=True)
class TraceCancellation:
    """Record original annual cancellation observations.

    Args:
        trace: Original ordered operation observations.
    """

    trace: list[str]

    def check(self) -> None:
        """Observe the original cancellation boundary."""
        _cancel(self.trace)


async def _execute(retry: AnnualRetry, trace: list[str]) -> int:
    for attempt in retry.attempts("description"):
        async with attempt:
            return _operation(trace)
    raise AssertionError("Retry scopes must include an attempt")
