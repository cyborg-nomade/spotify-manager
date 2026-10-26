"""Simple data-owned runtime resources for offline behavior checks."""

from collections.abc import Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Never
from typing import Protocol

import pytest

from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.retry_attempts import RetryAttempts
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import RetryNotice


@dataclass(frozen=True)
class MessageList:
    """Keep original message observations in the caller's list.

    Args:
        messages: Existing ordered message authority.
    """

    messages: list[str]

    def echo(self, message: str) -> None:
        """Record the original message without copying or reformatting it.

        Args:
            message: Complete original text.
        """
        self.messages.append(message)


class RetryRecorder(Protocol):
    """Record the original request boundary in an existing fixture authority."""

    def record(self, event: str, *values: object) -> None:
        """Record original ordered retry observations.

        Args:
            event: Original event name.
            values: Original event details.
        """
        ...


@dataclass(frozen=True)
class RecordedRequests:
    """Execute one direct scope after the original retry-label observation.

    Args:
        recorder: Existing fixture trace authority.
    """

    recorder: RetryRecorder

    def attempts(self, description: str) -> Iterator[AbstractContextManager[None]]:
        """Record the original retry boundary before returning its direct scope.

        Args:
            description: Original request label.

        Returns:
            One direct request scope.
        """
        self.recorder.record("retry", description)
        return NoRetry().attempts(description)


class TextProgress(Protocol):
    """Observe a fixture's distinct stage-progress channel."""

    def progress(self, message: str) -> None:
        """Record an original stage-progress message.

        Args:
            message: Original progress description.
        """
        ...


@dataclass(frozen=True)
class ProgressMessages:
    """Keep stage-progress output separate from accepted-effect messages.

    Args:
        observer: Fixture owning the original progress channel.
    """

    observer: TextProgress

    def echo(self, message: str) -> None:
        """Record the original progress message through its named channel.

        Args:
            message: Complete original description.
        """
        self.observer.progress(message)


@dataclass(frozen=True)
class DelayList:
    """Record waits in the caller's existing observation list.

    Args:
        delays: Original ordered wait durations.
    """

    delays: list[float]

    def sleep(self, seconds: float) -> None:
        """Record the original requested delay.

        Args:
            seconds: Original wait duration.
        """
        self.delays.append(seconds)


class DiscardMessages:
    """Accept messages when the original fixture discards output."""

    def echo(self, message: str) -> None:
        """Discard one original message.

        Args:
            message: Original ignored output.
        """


@dataclass(frozen=True)
class CancellationFlag:
    """Keep a fixture's fixed original cancellation response.

    Args:
        cancelled: Original cancellation state.
    """

    cancelled: bool

    def is_set(self) -> bool:
        """Return the original cancellation state.

        Returns:
            Whether this fixture is cancelled.
        """
        return self.cancelled


@dataclass(frozen=True)
class Answer:
    """Return a fixed scripted operator answer.

    Args:
        value: Original chosen control or identity.
    """

    value: str

    def choose_release(self, *values: object) -> str:
        """Return the scripted release choice.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_endpoint(self, *values: object) -> str:
        """Return the scripted endpoint choice.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_track(self, *values: object) -> str:
        """Return the scripted track choice.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_artist(self, *values: object) -> str:
        """Return the scripted artist choice.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_album(self, *values: object) -> str:
        """Return the scripted album choice.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_mode(self, *values: object) -> str:
        """Return the scripted selection mode.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_transition(self, *values: object) -> str:
        """Return the scripted transition choice.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_composer(self, *values: object) -> str:
        """Return the scripted composer choice.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value

    def choose_action(self, *values: object) -> str:
        """Return the scripted review action.

        Args:
            values: Original prompt context.

        Returns:
            Original fixed answer.
        """
        return self.value


@dataclass(frozen=True)
class UnexpectedInteraction:
    """Reject an operator prompt that the original scenario must never reach.

    Args:
        message: Original fixture failure explanation.
    """

    message: str

    def choose_release(self, *values: object) -> Never:
        """Reject an unexpected release choice.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_endpoint(self, *values: object) -> Never:
        """Reject an unexpected endpoint choice.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_track(self, *values: object) -> Never:
        """Reject an unexpected track choice.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_artist(self, *values: object) -> Never:
        """Reject an unexpected artist choice.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_album(self, *values: object) -> Never:
        """Reject an unexpected album choice.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_mode(self, *values: object) -> Never:
        """Reject an unexpected selection mode.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_transition(self, *values: object) -> Never:
        """Reject an unexpected transition choice.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_composer(self, *values: object) -> Never:
        """Reject an unexpected composer choice.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def choose_action(self, *values: object) -> Never:
        """Reject an unexpected review action.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def order_releases(self, *values: object) -> Never:
        """Reject an unexpected release-order prompt.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def complete(self, *values: object) -> Never:
        """Reject an unexpected completion notification.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def select_releases(self, *values: object) -> Never:
        """Reject an unexpected release-selection prompt.

        Args:
            values: Original prompt context.

        Raises:
            BaseException: Pytest reports the original unexpected interaction.
        """
        pytest.fail(self.message)

    def sample(self, *values: object) -> Never:
        """Reject an unexpected sample observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def now(self, *values: object) -> Never:
        """Reject an unexpected now observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def read(self, *values: object) -> Never:
        """Reject an unexpected read observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def progress(self, *values: object) -> Never:
        """Reject an unexpected progress observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def echo(self, *values: object) -> Never:
        """Reject an unexpected echo observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def is_set(self, *values: object) -> Never:
        """Reject an unexpected is set observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def wait(self, *values: object) -> Never:
        """Reject an unexpected wait observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def sleep(self, *values: object) -> Never:
        """Reject an unexpected sleep observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)

    def attempts(self, *values: object) -> Never:
        """Reject an unexpected attempts observation.

        Args:
            values: Original resource observation values.

        Raises:
            BaseException: Pytest reports the original unexpected observation.
        """
        pytest.fail(self.message)


class NoWait:
    """Discard retry waits at the original no-delay test boundary."""

    def sleep(self, seconds: float) -> None:
        """Accept the original ignored wait.

        Args:
            seconds: Original requested delay.
        """


@dataclass(frozen=True)
class FixedInstant:
    """Return a fixture's original calendar observation.

    Args:
        value: Original fixed instant.
    """

    value: datetime

    def now(self) -> datetime:
        """Return the original instant.

        Returns:
            Original fixed calendar value.
        """
        return self.value


@dataclass(frozen=True)
class FixedIndexes:
    """Return the fixture's original external random response.

    Args:
        value: Original indexes and generation timestamp.
    """

    value: RandomIndexSet

    def sample(self, population: int, count: int) -> RandomIndexSet:
        """Return the original index observation.

        Args:
            population: Original eligible population size.
            count: Original requested index count.

        Returns:
            Original external random response.
        """
        return self.value


@dataclass(frozen=True)
class ProgressDetails:
    """Record review details when the original fixture ignores counts.

    Args:
        messages: Original progress observations.
    """

    messages: list[str]

    def progress(self, completed: int, total: int, detail: str) -> None:
        """Record the original progress text.

        Args:
            completed: Original completed count.
            total: Original expected count.
            detail: Original detail text.
        """
        self.messages.append(detail)


@dataclass(frozen=True)
class AnalysisEvents:
    """Record complete resource-analysis progress values.

    Args:
        events: Original ordered progress observations.
    """

    events: list[tuple[ResourceName, int, int | None, str]]

    def progress(
        self, resource: ResourceName, completed: int, total: int | None, detail: str
    ) -> None:
        """Record the original analysis progress tuple.

        Args:
            resource: Original resource family.
            completed: Original completed count.
            total: Original expected count.
            detail: Original status detail.
        """
        self.events.append((resource, completed, total, detail))


@dataclass(frozen=True)
class RetryDecision:
    """Supply the original fixed retry decision and optional notice observations.

    Args:
        accepted: Original retry-versus-stop answer.
        notices: Original optional notice recording list.
    """

    accepted: bool
    notices: list[RetryNotice] | None = None

    def wait(self, notice: RetryNotice) -> bool:
        """Record the notice and return the original decision.

        Args:
            notice: Original retry status and wait details.

        Returns:
            Original retry decision.
        """
        if self.notices is not None:
            self.notices.append(notice)
        return self.accepted


class RetryRuntimeOnce:
    """Repeat a direct request once after the fixture's original RuntimeError."""

    def attempts(self, description: str) -> RetryAttempts:
        """Create independent failure state for the original retry boundary.

        Args:
            description: Original request label.

        Returns:
            Scopes retaining the original one-retry behavior.
        """
        return RetryAttempts(_RuntimeOncePolicy())


@dataclass
class _RuntimeOncePolicy:
    retried: bool = False

    def start(self) -> None:
        """Enter the original request without additional observations."""

    def accepted(self) -> None:
        """Accept the original response without additional observations."""

    def failed(self, error: BaseException) -> bool:
        """Retry the original RuntimeError once.

        Args:
            error: Original request failure.

        Returns:
            Whether the original one-shot retry is still available.
        """
        if self.retried or not isinstance(error, RuntimeError):
            return False
        self.retried = True
        return True


@dataclass(frozen=True)
class CountEvents:
    """Record the original completed and expected review counts.

    Args:
        events: Original progress observations.
    """

    events: list[tuple[int, int]]

    def progress(self, completed: int, total: int) -> None:
        """Record the original progress pair.

        Args:
            completed: Original completed count.
            total: Original expected count.
        """
        self.events.append((completed, total))


class UnexpectedCall(UnexpectedInteraction):
    """Reject an external framework callback that the fixture must never reach.

    Args:
        message: Original unexpected-call explanation.
    """

    def __call__(self, *args: object, **kwargs: object) -> Never:
        """Fail at the original unexpected external call boundary.

        Args:
            args: Original external positional arguments.
            kwargs: Original external named arguments.

        Raises:
            BaseException: Pytest reports the original unexpected call.
        """
        pytest.fail(self.message)
