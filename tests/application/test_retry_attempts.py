"""Preserve retry entry, acceptance and failure order without executable inputs."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.retry_attempts import CheckedAttempts
from spotify_manager.application.retry_attempts import RetryAttempts


@dataclass
class RecordedPolicy:
    """Record accepted retry boundaries using explicit methods.

    Args:
        retryable: Failure permitted to repeat.
        events: Ordered entry, failure and acceptance observations.
    """

    retryable: type[BaseException] = RuntimeError
    events: list[object] = field(default_factory=list)

    def start(self) -> None:
        """Record one entry before any operation attempt."""
        self.events.append("start")

    def accepted(self) -> None:
        """Record acceptance after the successful operation."""
        self.events.append("accepted")

    def failed(self, error: BaseException) -> bool:
        """Record the same failure before deciding whether to repeat.

        Args:
            error: Original failure object.

        Returns:
            Whether this policy permits another attempt.
        """
        self.events.append(error)
        return isinstance(error, self.retryable)


def test_retry_scopes_repeat_the_direct_operation_after_an_accepted_failure() -> None:
    """Retain one entry observation and acceptance only after the final attempt."""
    policy = RecordedPolicy()
    failure = RuntimeError("repeat")
    operation = ScriptedRequest(failure)
    for attempt in RetryAttempts(policy):
        with attempt:
            operation.execute()
    assert operation.calls == 2
    assert policy.events == ["start", failure, "accepted"]


def test_retry_scope_propagates_the_same_nonretryable_failure() -> None:
    """Keep failure identity, context and cause when a policy declines retry."""
    policy = RecordedPolicy()
    failure = ValueError("terminal")
    with pytest.raises(ValueError) as raised:
        _raise_in_scope(policy, failure)
    assert raised.value is failure
    assert raised.value.__cause__ is None
    assert policy.events == ["start", failure]


def _raise_in_scope(policy: RecordedPolicy, failure: BaseException) -> None:
    for attempt in RetryAttempts(policy):
        with attempt:
            raise failure


def test_direct_scope_runs_once_without_translating_process_control() -> None:
    """Retain direct-operation semantics for a disabled retry policy."""
    failure = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as raised:
        _raise_without_retry(failure)
    assert raised.value is failure


def _raise_without_retry(failure: BaseException) -> None:
    for attempt in NoRetry().attempts("direct request"):
        with attempt:
            raise failure


def test_retry_scope_stops_after_a_direct_success() -> None:
    """Do not repeat an accepted operation when the caller continues its loop."""
    policy = RecordedPolicy()
    operations = 0
    for attempt in RetryAttempts(policy):
        with attempt:
            operations += 1
    assert operations == 1
    assert policy.events == ["start", "accepted"]


@dataclass
class ScriptedRequest:
    """Observe the original one-shot failure before a successful direct attempt.

    Args:
        failure: Original first request failure.
        calls: Original request attempt count.
    """

    failure: BaseException
    calls: int = 0

    def execute(self) -> None:
        """Fail the original first request and accept the following request.

        Raises:
            BaseException: The original first-request failure.
        """
        self.calls += 1
        if self.calls == 1:
            raise self.failure


@dataclass
class CancellationProbe:
    """Record post-success cancellation without hiding the request execution.

    Args:
        failure: Optional original cancellation error.
        checks: Number of observed cancellation boundaries.
    """

    failure: RuntimeError | None = None
    checks: int = 0

    def check(self) -> None:
        """Observe the original successful-request cancellation boundary.

        Raises:
            RuntimeError: The original cancellation signal is set.
        """
        self.checks += 1
        if self.failure is not None:
            raise self.failure


def _accepted_value(attempts: Iterator[AbstractContextManager[None]]) -> str:
    for attempt in attempts:
        with attempt:
            return "accepted"
    raise AssertionError("A direct request must provide an attempt")


def test_checked_scope_observes_cancellation_even_after_a_return() -> None:
    """Retain the original post-request check before returning the accepted result."""
    cancellation = CancellationProbe()
    attempts = CheckedAttempts(NoRetry().attempts("request"), cancellation)
    assert _accepted_value(attempts) == "accepted"
    assert cancellation.checks == 1


def test_checked_scope_preserves_cancellation_failure_identity() -> None:
    """Propagate original post-success cancellation without accepting the return."""
    failure = RuntimeError("cancelled after acceptance")
    cancellation = CancellationProbe(failure)
    attempts = CheckedAttempts(NoRetry().attempts("request"), cancellation)
    with pytest.raises(RuntimeError) as raised:
        _accepted_value(attempts)
    assert raised.value is failure
    assert cancellation.checks == 1


def _failed_request(
    attempts: Iterator[AbstractContextManager[None]], failure: BaseException
) -> None:
    for attempt in attempts:
        with attempt:
            raise failure


def test_checked_scope_skips_post_success_check_after_request_failure() -> None:
    """Retain the request failure without an extra cancellation observation."""
    failure = ValueError("request failed")
    cancellation = CancellationProbe()
    attempts = CheckedAttempts(NoRetry().attempts("request"), cancellation)
    with pytest.raises(ValueError) as raised:
        _failed_request(attempts, failure)
    assert raised.value is failure
    assert cancellation.checks == 0
