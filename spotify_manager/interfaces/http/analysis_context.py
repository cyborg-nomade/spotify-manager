"""Named synchronization and log resources for analysis workers."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from threading import Lock

from spotify_manager.application.job_lifecycle import append_log
from spotify_manager.application.job_lifecycle import retain_logs
from spotify_manager.interfaces.http.job_records import AnalysisJob
from spotify_manager.interfaces.http.logging import JobLogFormatter


@dataclass(frozen=True)
class AnalysisContext:
    """Own one worker's synchronization, time and accepted logs.

    Args:
        lock: Existing registry lock.
        clock: Original caller-owned clock type.
        log_limit: Original retained log bound.
    """

    lock: Lock
    clock: type[datetime]
    log_limit: int

    def now(self) -> datetime:
        """Observe the original UTC job clock.

        Returns:
            Current UTC instant.
        """
        return self.clock.now(UTC)

    def append(self, job: AnalysisJob, message: str) -> None:
        """Append an accepted event while the caller holds the registry lock.

        Args:
            job: Registered analysis handle.
            message: Complete unmodified text; empty messages are ignored.
        """
        if not message:
            return
        job.next_log_sequence = append_log(
            job.result.logs, job.next_log_sequence, message, JobLogFormatter(self.clock)
        )
        retain_logs(job.result.logs, self.log_limit)
