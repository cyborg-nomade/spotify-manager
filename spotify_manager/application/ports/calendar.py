"""Local calendar observations consumed by listening policies."""

from datetime import date
from datetime import datetime
from typing import Protocol


class ListeningCalendar(Protocol):
    """Translate an observed instant or read today's local calendar date."""

    def local_date(self, value: datetime | date | None = None) -> date:
        """Observe the local date before applying listening-week rules.

        Args:
            value: Existing timestamp/date, or None for a fresh clock read.

        Returns:
            Local date with the original naive-timestamp interpretation.
        """
