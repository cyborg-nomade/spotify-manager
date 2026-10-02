"""Seed request validation and week observation independent of external services."""

from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import cast

import pytest

from spotify_manager.application.found_art_values import FoundArtConfigError
from spotify_manager.application.found_art_values import FoundArtStateError
from spotify_manager.application.recommendation_seeds import RecommendationSeeds
from spotify_manager.domain.recommendation_history import TrackHistory
from tests.support.recommendation_seeds import seed_cases
from tests.support.recommendation_seeds import seed_history
from tests.support.recommendation_seeds import seed_records


WEEK = date(2026, 7, 17)


@dataclass
class SeedMemory:
    """Observe history consumption before any requested week read.

    Args:
        tracks: Original ordered history.
        events: Observed consumption and calendar reads.
        failure: Whether the week read fails.
    """

    tracks: list[TrackHistory] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    failure: bool = False

    def history(self) -> Iterator[TrackHistory]:
        """Yield all input statistics after observing the first materialization.

        Yields:
            Original ordered history records.
        """
        self.events.append("history")
        yield from self.tracks

    def week(self) -> date:
        """Resolve the effective week after input validation.

        Returns:
            Stable original listening week.

        Raises:
            OSError: The scripted calendar observation fails.
        """
        self.events.append("week")
        if self.failure:
            raise OSError("calendar")
        return WEEK


@pytest.mark.parametrize("case", seed_cases())
def test_application_seed_decisions_and_errors_match_original(
    case: dict[str, object],
) -> None:
    """Retain exact original decisions and original error types/messages.

    Args:
        case: Captured original seed case.
    """
    memory = SeedMemory(seed_history(case))
    workflow = RecommendationSeeds(memory.week)
    count = cast(int, case["seed_count"])
    if "error" in case:
        with pytest.raises(FoundArtStateError) as error:
            workflow.run(memory.history(), count, WEEK)
        assert str(error.value) == case["error"]
        assert memory.events == ["history"]
        return
    assert seed_records(workflow.run(memory.history(), count, WEEK)) == case["seeds"]
    assert memory.events == ["history"]


@pytest.mark.parametrize("count", [0, -1])
def test_invalid_count_precedes_history_materialization(count: int) -> None:
    """Reject invalid counts without advancing an input generator or calendar.

    Args:
        count: Invalid requested seed count.
    """
    memory = SeedMemory()
    with pytest.raises(FoundArtConfigError, match="at least 1"):
        RecommendationSeeds(memory.week).run(memory.history(), count, None)
    assert memory.events == []


def test_empty_history_precedes_week_observation() -> None:
    """Materialize empty history once, then preserve the original state error."""
    memory = SeedMemory()
    with pytest.raises(FoundArtStateError, match="No tracks are available"):
        RecommendationSeeds(memory.week).run(memory.history(), 1, None)
    assert memory.events == ["history"]


def test_default_week_is_observed_after_consuming_history() -> None:
    """Read the calendar only after valid ordered input is materialized."""
    case = seed_cases()[0]
    memory = SeedMemory(seed_history(case))
    result = RecommendationSeeds(memory.week).run(
        memory.history(), cast(int, case["seed_count"]), None
    )
    assert memory.events == ["history", "week"]
    assert seed_records(result) == case["seeds"]


def test_calendar_failure_preserves_original_exception() -> None:
    """Do not wrap a caller's week observation failure in a recommendation error."""
    memory = SeedMemory(seed_history(seed_cases()[0]), failure=True)
    with pytest.raises(OSError, match="calendar"):
        RecommendationSeeds(memory.week).run(memory.history(), 1, None)
    assert memory.events == ["history", "week"]
