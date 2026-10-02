"""Protect Queue request validation before consuming history or reading the week."""

from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field
from datetime import date

import pytest

from spotify_manager.application.queue_seeds import QueueSeeds
from spotify_manager.application.queue_values import QueueConfigError
from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.domain.queue_values import ArtistHistory


WEEK = date(2026, 8, 7)
ARTIST = ArtistHistory("Artist", "artist", 100, 90, 100, 1000)


@dataclass
class Observations:
    """Record history consumption and the original lazy week boundary.

    Args:
        events: Ordered observation trace.
    """

    events: list[str] = field(default_factory=list)

    def __iter__(self) -> Iterator[ArtistHistory]:
        """Consume the original one-use history source.

        Returns:
            Iterator recording its consumption.
        """
        self.events.append("history")
        yield ARTIST

    def week(self) -> date:
        """Observe the original effective-week boundary.

        Returns:
            Fixed original listening week.
        """
        self.events.append("week")
        return WEEK


def test_queue_invalid_count_precedes_history_consumption_and_week() -> None:
    """Reject an invalid count before any external or iterable observation."""
    observations = Observations()
    with pytest.raises(QueueConfigError, match="at least 1"):
        QueueSeeds(observations.week).select(observations, 0, None)
    assert observations.events == []


def test_queue_insufficient_history_precedes_week_resolution() -> None:
    """Check available history before asking for the effective listening week."""
    observations = Observations()
    with pytest.raises(QueueStateError, match="Only 1 seed artists.*2 requested"):
        QueueSeeds(observations.week).select(observations, 2, None)
    assert observations.events == ["history"]


@pytest.mark.parametrize("explicit", [False, True])
def test_queue_effective_week_is_resolved_once_only_when_needed(explicit: bool) -> None:
    """Preserve materialization order and explicit-week authority.

    Args:
        explicit: Supply the original effective week directly.
    """
    observations = Observations()
    seeds = QueueSeeds(observations.week).select(
        observations, 1, WEEK if explicit else None
    )
    assert seeds[0].artist == "Artist"
    assert observations.events == (["history"] if explicit else ["history", "week"])
