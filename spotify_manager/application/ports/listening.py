"""History and function-shaped ports for interaction, audit, and time."""

from collections.abc import Callable
from datetime import date
from datetime import datetime
from typing import Protocol

from spotify_manager.domain.history import Scrobble


# These effects need no object hierarchy: existing callbacks implement the ports.
type MessageSink = Callable[[str], None]
type ChoiceReader[Context, Choices] = Callable[[Context, Choices], str]
type AuditWriter[Result] = Callable[[Result], None]
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
