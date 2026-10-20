"""History and function-shaped ports for interaction, audit, and time."""

from collections.abc import Callable
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.domain.history import Scrobble


# Interactions, time observations and retry operations retain genuine hooks.
type MessageSink = Callable[[str], None]
type ChoiceReader[Context, Choices] = Callable[[Context, Choices], str]
type Clock = Callable[[], datetime]
type RandomTimestamp = Callable[[], datetime]
type RetryCall = Callable[[Callable[[], object], str], object]


class ListeningHistory(Protocol):
    """Read parsed listening events without exposing export files to use cases."""

    def by_date(self) -> dict[date, tuple[Scrobble, ...]]:
        """Read events grouped by the existing Berlin-local date rules.

        Returns:
            Original events and ordering inside each date bucket.
        """


class AuditWriter[Result](Protocol):
    """Persist complete routine audit outcomes."""

    def write(self, result: Result) -> None:
        """Accept a complete audit record.

        Args:
            result: Completed routine outcome.
        """
        ...
