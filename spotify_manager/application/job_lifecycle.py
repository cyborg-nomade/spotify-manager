"""Share original job identity, conflict selection and accepted log boundaries."""

from collections.abc import Callable
from collections.abc import Iterable
from typing import Protocol


ACTIVE_STATUSES = {"queued", "running", "waiting", "cancelling"}


class JobIdentity(Protocol):
    """Expose only the original metadata needed to decide a start conflict."""

    @property
    def job_id(self) -> str:
        """Read the original opaque handle.

        Returns:
            Process-local job identity.
        """
        ...

    @property
    def command(self) -> str:
        """Read the original command identity.

        Returns:
            Existing adapter command without normalization.
        """
        ...

    @property
    def status(self) -> str:
        """Read the currently observed original job phase.

        Returns:
            Current phase, including terminal or unknown legacy values.
        """
        ...


class WaitSignal(Protocol):
    """Expose the caller-owned submission signal without a thread dependency."""

    def wait(self, timeout: float | None = None) -> bool:
        """Wait for the original signal or polling timeout.

        Args:
            timeout: Maximum wait in seconds.

        Returns:
            Whether the signal is set after the wait.
        """
        ...


def await_submission[T](signal: WaitSignal, consume: Callable[[], T | None]) -> T:
    """Poll and consume an interaction at the original locked safe boundary.

    Args:
        signal: Existing job-owned event, including its original clearing semantics.
        consume: Adapter callback acquiring its lock and checking cancellation.

    Returns:
        First accepted submission, including an empty string or empty tuple.

    Raises:
        RuntimeError: The owning adapter signals cancellation during consumption.
    """
    while True:
        signal.wait(0.5)
        submission = consume()
        if submission is not None:
            return submission


def first_active_job(
    jobs: Iterable[JobIdentity], command: str | None = None
) -> JobIdentity | None:
    """Select the first original conflict in registry encounter order.

    Args:
        jobs: Lazy metadata observations supplied while the owner holds its lock.
        command: Exact analysis command to match, or the full playlist/history scope.

    Returns:
        First matching active handle, or none without observing later rows.
    """
    for job in jobs:
        if is_active_job(job, command):
            return job
    return None


def is_active_job(job: JobIdentity, command: str | None = None) -> bool:
    """Apply the original command guard before observing the active phase.

    Args:
        job: Metadata supplied by the registry owner.
        command: Exact command filter, or none to observe the entire registry.

    Returns:
        Whether the original command and phase permit an active observation.
    """
    if command is not None and job.command != command:
        return False
    return job.status in ACTIVE_STATUSES


def append_log[T](
    entries: list[T],
    sequence: int,
    message: str,
    create: Callable[[int, str], T],
) -> int:
    """Accept one original log entry before advancing its sequence.

    Args:
        entries: Caller-owned log authority; no second log buffer is introduced.
        sequence: Next original monotonically increasing sequence.
        message: Original unmodified text; an empty message observes no factory.
        create: Clock and presentation boundary constructing the accepted entry.

    Returns:
        Next sequence after accepted append, or the unchanged value for no message.
        Factory failures propagate before any append or sequence advancement.
    """
    if not message:
        return sequence
    entries.append(create(sequence, message))
    return sequence + 1


def retain_logs[T](entries: list[T], maximum: int) -> None:
    """Trim the original oldest accepted entries after sequence advancement.

    Args:
        entries: Original mutable log buffer.
        maximum: Original retention bound, preserving zero/negative boundary behavior.
    """
    if len(entries) > maximum:
        del entries[: len(entries) - maximum]
