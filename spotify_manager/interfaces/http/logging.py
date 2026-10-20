"""Clock-owned presentation of HTTP job log entries."""

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime

from spotify_manager.interfaces.http.models.analysis import AnalysisJobLog


@dataclass(frozen=True)
class JobLogFormatter:
    """Observe the supplied clock when a log entry is accepted.

    Args:
        clock: Original caller-owned clock type.
    """

    clock: type[datetime]

    def create(self, sequence: int, message: str) -> AnalysisJobLog:
        """Create a timestamped log entry.

        Args:
            sequence: Next accepted sequence.
            message: Complete unmodified message.

        Returns:
            Original validated log entry.
        """
        return AnalysisJobLog(
            sequence=sequence,
            timestamp=self.clock.now(UTC).isoformat(),
            message=message,
        )
