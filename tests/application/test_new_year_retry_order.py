"""Verify original direct and falsey caller retry timing around cancellation checks."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from spotify_manager.application.new_year_retry import AnnualRetry


def _cancel(trace: list[str]) -> None:
    trace.append("cancel")


def _operation(trace: list[str]) -> int:
    trace.append("operation")
    return 11


def test_annual_missing_caller_retry_runs_operation_between_cancellation_checks() -> (
    None
):
    """Retain original direct invocation and both cancellation boundaries."""
    trace: list[str] = []
    retry = AnnualRetry(None, partial(_cancel, trace))
    assert retry.run(partial(_operation, trace), "description") == 11
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

    def __call__(self, operation: Callable[[], object], description: str) -> object:
        """Reject an unexpected call to the original falsey retry boundary.

        Args:
            operation: Original deferred operation.
            description: Original retry label.

        Raises:
            AssertionError: Original falsey callers must use direct invocation.
        """
        raise AssertionError("falsey caller must not execute")


def test_annual_falsey_retry_is_checked_only_after_first_cancellation_boundary() -> (
    None
):
    """Retain original late truthiness and direct operation semantics."""
    trace: list[str] = []
    retry = AnnualRetry(FalseyRetry(trace), partial(_cancel, trace))
    assert trace == []
    assert retry.run(partial(_operation, trace), "description") == 11
    assert trace == ["cancel", "truthiness", "operation", "cancel"]
