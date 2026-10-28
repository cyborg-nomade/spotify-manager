"""History and function-shaped ports for interaction, audit, and time."""

from datetime import date
from typing import Protocol

from spotify_manager.application.ports.runtime import Clock as Clock
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.application.ports.runtime import Retry
from spotify_manager.domain.history import Scrobble


type RandomTimestamp = Clock


type MessageSink = Messages


type RetryCall = Retry


# Interactions, time observations and retry operations retain genuine hooks.


class ListeningHistory(Protocol):
    """Read parsed listening events without exposing export files to use cases."""

    async def by_date(self) -> dict[date, tuple[Scrobble, ...]]:
        """Read events grouped by the existing Berlin-local date rules.

        Returns:
            Original events and ordering inside each date bucket.
        """


class AuditWriter[Result](Protocol):
    """Persist complete routine audit outcomes."""

    async def write(self, result: Result) -> None:
        """Accept a complete audit record.

        Args:
            result: Completed routine outcome.
        """
        ...
