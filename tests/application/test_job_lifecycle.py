"""Exercise conflict observation order and accepted-log failure boundaries."""

from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.job_lifecycle import JobIdentity
from spotify_manager.application.job_lifecycle import append_log
from spotify_manager.application.job_lifecycle import await_submission
from spotify_manager.application.job_lifecycle import first_active_job
from spotify_manager.application.job_lifecycle import retain_logs


@dataclass
class SubmissionProbe:
    """Record event waits and consumption without threads or real delays.

    Args:
        values: Ordered submissions, including missing or empty values.
        observations: Original wait and consumption order.
        index: Next scripted observation.
    """

    values: tuple[str | None, ...]
    observations: list[str] = field(default_factory=list)
    index: int = 0

    def wait(self, timeout: float | None = None) -> bool:
        """Record the polling wait.

        Args:
            timeout: Original polling delay.

        Returns:
            False, demonstrating that consumption still follows an unset signal.
        """
        self.observations.append(f"wait:{timeout}")
        return False

    def consume(self) -> str | None:
        """Consume the next scripted value.

        Returns:
            Original submission, including an empty string or no submission.
        """
        self.observations.append("consume")
        value = self.values[self.index]
        self.index += 1
        return value


def cancelled_submission() -> str | None:
    """Signal a safe cancellation boundary.

    Raises:
        RuntimeError: The original job was cancelled.
    """
    raise RuntimeError("cancelled")


def test_submission_waits_before_each_consumption_and_accepts_empty_text() -> None:
    """Keep timeout polling, consumption order and empty submission acceptance."""
    probe = SubmissionProbe((None, ""))
    assert await_submission(probe, probe.consume) == ""
    assert probe.observations == ["wait:0.5", "consume", "wait:0.5", "consume"]


def test_submission_propagates_cancellation_after_the_original_wait() -> None:
    """Leave cancellation and pending-view cleanup with the owning adapter."""
    probe = SubmissionProbe(())
    with pytest.raises(RuntimeError, match="cancelled"):
        await_submission(probe, cancelled_submission)
    assert probe.observations == ["wait:0.5"]


@dataclass
class ObservedJob:
    """Expose job facts while recording exactly which fields are observed.

    Args:
        identity: Opaque original handle.
        name: Original command.
        phase: Current original status.
        observations: Ordered metadata reads.
    """

    identity: str
    name: str
    phase: str
    observations: list[str] = field(default_factory=list)

    @property
    def job_id(self) -> str:
        """Return the observed handle.

        Returns:
            Original identity.
        """
        self.observations.append("identity")
        return self.identity

    @property
    def command(self) -> str:
        """Return the observed command.

        Returns:
            Original command.
        """
        self.observations.append("command")
        return self.name

    @property
    def status(self) -> str:
        """Return the observed phase.

        Returns:
            Original status.
        """
        self.observations.append("status")
        return self.phase


def unavailable_tail(first: JobIdentity) -> Iterator[JobIdentity]:
    """Fail only if conflict selection observes beyond the accepted first row.

    Args:
        first: Original first matching active metadata.

    Yields:
        The first original metadata row.

    Raises:
        RuntimeError: A later row is unnecessarily observed.
    """
    yield first
    raise RuntimeError("later metadata is unavailable")


def test_first_conflict_stops_before_observing_later_metadata() -> None:
    """Preserve lazy first-conflict selection and the playlist status-first order."""
    job = ObservedJob("first", "playlist", "waiting")
    selected = first_active_job(unavailable_tail(job))
    assert selected is job
    assert job.observations == ["status"]
    assert selected.job_id == "first"


def test_analysis_skips_status_of_a_nonmatching_command() -> None:
    """Observe the command guard before status only for analysis-scoped starts."""
    unrelated = ObservedJob("one", "other", "running")
    matching = ObservedJob("two", "analysis", "queued")
    assert first_active_job((unrelated, matching), "analysis") is matching
    assert unrelated.observations == ["command"]
    assert matching.observations == ["command", "status"]


@pytest.mark.parametrize(
    "phase", ("completed", "paused", "cancelled", "failed", "unknown")
)
def test_terminal_and_unknown_phases_leave_no_conflict(phase: str) -> None:
    """Preserve absence of a conflict without requiring stricter phase validation.

    Args:
        phase: Original non-active observed status.
    """
    job = ObservedJob("one", "command", phase)
    assert first_active_job((job,)) is None
    assert first_active_job(()) is None


@dataclass(frozen=True)
class Entry:
    """Represent one accepted internal log value.

    Args:
        sequence: Original next sequence.
        message: Original unmodified message.
    """

    sequence: int
    message: str


@dataclass
class EntryFactory:
    """Record construction and optionally fail before log acceptance.

    Args:
        fail: Reject construction before append.
        observations: Original construction arguments.
    """

    fail: bool = False
    observations: list[tuple[int, str]] = field(default_factory=list)

    def __call__(self, sequence: int, message: str) -> Entry:
        """Construct one portable log entry at the explicit boundary.

        Args:
            sequence: Original next sequence.
            message: Original unchanged message.

        Returns:
            Newly accepted entry.

        Raises:
            RuntimeError: Construction fails before acceptance.
        """
        self.observations.append((sequence, message))
        if self.fail:
            raise RuntimeError("log construction failed")
        return Entry(sequence, message)


def test_empty_message_observes_no_clock_or_factory() -> None:
    """Retain the original no-op before any log construction."""
    factory = EntryFactory(fail=True)
    entries: list[Entry] = []
    assert append_log(entries, 7, "", factory) == 7
    assert entries == []
    assert factory.observations == []


def test_accepted_log_advances_without_normalizing_text() -> None:
    """Keep whitespace messages and accepted sequence values exactly as supplied."""
    factory = EntryFactory()
    entries: list[Entry] = []
    assert append_log(entries, 7, "  ", factory) == 8
    assert entries == [Entry(7, "  ")]
    assert factory.observations == [(7, "  ")]


def test_failed_log_construction_does_not_accept_or_advance() -> None:
    """Keep the original authority unchanged when the boundary rejects an entry."""
    entries = [Entry(6, "previous")]
    sequence = 7
    with pytest.raises(RuntimeError, match="log construction failed"):
        sequence = append_log(entries, sequence, "new", EntryFactory(fail=True))
    assert sequence == 7
    assert entries == [Entry(6, "previous")]


@pytest.mark.parametrize(
    ("entries", "maximum", "expected"),
    (
        ([], 250, []),
        ([1, 2], 2, [1, 2]),
        ([1, 2, 3], 2, [2, 3]),
        ([1, 2], 0, []),
        ([1, 2], -1, []),
    ),
)
def test_retention_keeps_original_order_and_boundaries(
    entries: list[int], maximum: int, expected: list[int]
) -> None:
    """Trim in place without resetting sequence authority or adding validation.

    Args:
        entries: Caller-owned original buffer.
        maximum: Original retention boundary.
        expected: Original accepted tail.
    """
    original = entries
    retain_logs(entries, maximum)
    assert entries is original
    assert entries == expected
