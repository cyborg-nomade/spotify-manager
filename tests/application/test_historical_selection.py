"""Independent historical selection contracts over explicit loaded facts."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.application.historical_selection import AnniversarySelection
from spotify_manager.application.historical_selection import BlastSelection
from spotify_manager.application.historical_selection import HistoryByDate
from spotify_manager.application.historical_values import BlastFromPastError
from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.application.historical_values import RandomIndexSet
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import ScrobbleSelection
from spotify_manager.domain.history import anniversary_dates
from spotify_manager.domain.history import eligible_dates
from spotify_manager.domain.history import select_scrobble


STAMP = datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC)
FIRST_DATE = date(2007, 11, 27)


def _history() -> HistoryByDate:
    return {
        date(2025, 7, 22): [Scrobble("Newest", "Artist", "Album", 3)],
        date(2015, 7, 22): [Scrobble("Middle", "Artist", "Album", 2)],
        date(2010, 1, 1): [Scrobble("Anchor", "Artist", "Album", 1)],
    }


@dataclass
class SelectionMemory:
    """Record date selection boundaries without external randomness or files.

    Args:
        buckets: History in original bucket order.
        events: Observed operations.
        messages: Presented progress.
        indexes: Scripted random date indexes.
        date_indexes: Original indexes passed to track selection.
        requests: Random source populations and requested counts.
        failure: Observation that raises.
    """

    buckets: HistoryByDate = field(default_factory=_history)
    events: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    indexes: tuple[int, ...] = (1, 0)
    date_indexes: list[int] = field(default_factory=list)
    requests: list[tuple[int, int]] = field(default_factory=list)
    failure: str = ""

    def _step(self, name: str) -> None:
        self.events.append(name)
        if self.failure == name:
            raise OSError(name)

    def history(self) -> HistoryByDate:
        """Observe local history.

        Returns:
            Original caller-owned buckets.
        """
        self._step("history")
        return self.buckets

    def cutoff(self) -> date:
        """Observe the Friday cutoff after history loading.

        Returns:
            Inclusive historical cutoff.
        """
        self._step("cutoff")
        return date(2021, 12, 31)

    def today(self) -> date:
        """Observe the calendar after history loading.

        Returns:
            Effective local anniversary date.
        """
        self._step("today")
        return date(2026, 7, 22)

    def eligible(self, buckets: HistoryByDate, cutoff: date) -> list[date]:
        """Apply the existing inclusive date window.

        Args:
            buckets: Loaded history.
            cutoff: Inclusive cutoff.

        Returns:
            Populated dates in chronological order.
        """
        return eligible_dates(buckets, FIRST_DATE, cutoff)

    def random(self, population: int, count: int) -> RandomIndexSet:
        """Observe one random index request.

        Args:
            population: Eligible date count.
            count: Requested selection count.

        Returns:
            Scripted indexes and one shared timestamp.
        """
        self._step("random")
        self.requests.append((population, count))
        return RandomIndexSet(self.indexes, STAMP)

    def timestamp(self) -> datetime:
        """Observe one random timestamp request.

        Returns:
            Shared selection timestamp.
        """
        self._step("random")
        return STAMP

    def select(
        self, day: date, index: int, plays: list[Scrobble], stamp: datetime
    ) -> ScrobbleSelection:
        """Apply the original paging rule after recording the supplied date index.

        Args:
            day: Selected date.
            index: Original unfiltered date index.
            plays: Existing date bucket.
            stamp: Shared random timestamp.

        Returns:
            Selected play and explanatory positions.
        """
        self._step("select")
        self.date_indexes.append(index)
        assert stamp is STAMP
        return select_scrobble(day, index, plays, stamp)


def _blast(memory: SelectionMemory) -> BlastSelection:
    return BlastSelection(
        memory.history,
        memory.cutoff,
        memory.eligible,
        memory.random,
        memory.select,
        memory.messages.append,
    )


def _radio(memory: SelectionMemory) -> AnniversarySelection:
    return AnniversarySelection(
        memory.history,
        memory.today,
        anniversary_dates,
        memory.timestamp,
        memory.select,
        memory.messages.append,
    )


def test_blast_keeps_random_index_order_and_shared_timestamp() -> None:
    """Retain source index order and read one shared random timestamp."""
    memory = SelectionMemory()
    result = _blast(memory).run(2)
    assert memory.events == ["history", "cutoff", "random", "select", "select"]
    assert memory.requests == [(2, 2)] and memory.date_indexes == [1, 0]
    assert [selection.scrobble.track for selection in result.selections] == [
        "Middle",
        "Anchor",
    ]
    assert result.generated_at is STAMP and result.available_dates == 2
    assert result.cutoff_date == date(2021, 12, 31)
    assert memory.messages == [
        "Loading Last.fm scrobbles",
        "Requesting unique date indexes from Random.org",
        "Applying Last.fm pagination rules",
    ]


@pytest.mark.parametrize("count", [0, -1])
def test_blast_invalid_count_precedes_history_reads(count: int) -> None:
    """Reject invalid counts before loading or presenting history.

    Args:
        count: Invalid requested count.
    """
    memory = SelectionMemory()
    with pytest.raises(BlastFromPastError, match="at least 1"):
        _blast(memory).run(count)
    assert not memory.events and not memory.messages


@pytest.mark.parametrize("empty", [False, True])
def test_blast_population_validation_precedes_randomness(empty: bool) -> None:
    """Reject empty or insufficient populations after reading the cutoff.

    Args:
        empty: Whether history has no eligible dates.
    """
    memory = SelectionMemory(buckets={} if empty else _history())
    expected = "No scrobbled dates.*2021-12-31" if empty else "Count 3 exceeds the 2"
    with pytest.raises(BlastFromPastError, match=expected):
        _blast(memory).run(3)
    assert memory.events == ["history", "cutoff"]


@pytest.mark.parametrize(
    "indexes,expected", [((0, 0), [0, 0]), ((-1,), [-1]), ((), [])]
)
def test_blast_retains_original_random_boundary_tolerance(
    indexes: tuple[int, ...], expected: list[int]
) -> None:
    """Retain duplicate, negative and empty indexes from an injected random source.

    Args:
        indexes: Scripted raw indexes.
        expected: Track-selection indexes without extra validation.
    """
    memory = SelectionMemory(indexes=indexes)
    result = _blast(memory).run(1)
    assert memory.date_indexes == expected
    assert len(result.selections) == len(indexes)


def test_blast_out_of_range_index_retains_constructor_error() -> None:
    """An out-of-range injected index raises after the original progress messages."""
    memory = SelectionMemory(indexes=(2,))
    with pytest.raises(IndexError):
        _blast(memory).run(1)
    assert memory.events == ["history", "cutoff", "random"]
    assert memory.messages[-1] == "Applying Last.fm pagination rules"


def test_radio_missing_dates_keep_unfiltered_indexes() -> None:
    """Missing anniversary buckets retain their positions in subsequent selections."""
    memory = SelectionMemory()
    result = _radio(memory).run()
    assert memory.events == ["history", "today", "random", "select", "select"]
    assert memory.date_indexes == [0, 2]
    assert result.generated_at is STAMP
    assert result.target_dates == (
        date(2025, 7, 22),
        date(2020, 7, 22),
        date(2015, 7, 22),
        date(2010, 7, 22),
    )
    assert result.missing_dates == (date(2020, 7, 22), date(2010, 7, 22))


def test_radio_empty_buckets_skip_randomness() -> None:
    """A known date with an empty bucket is missing, not a selectable population."""
    memory = SelectionMemory(buckets={date(2025, 7, 22): []})
    result = _radio(memory).run()
    assert memory.events == ["history", "today"]
    assert result.target_dates == result.missing_dates == (date(2025, 7, 22),)
    assert result.generated_at is None and not result.selections


def test_radio_empty_export_fails_before_clock_access() -> None:
    """Reject history without date buckets before resolving the effective date."""
    memory = SelectionMemory(buckets={})
    with pytest.raises(LastFmExportError, match="does not contain any scrobbles"):
        _radio(memory).run()
    assert memory.events == ["history"]


@pytest.mark.parametrize("kind", ["blast", "radio"])
@pytest.mark.parametrize("failure", ["history", "random", "select"])
def test_selection_failure_suppresses_later_observations(
    kind: str, failure: str
) -> None:
    """Propagate observation failures without replacing their type or retrying.

    Args:
        kind: Selection workflow.
        failure: Chosen observation failure.
    """
    memory = SelectionMemory(failure=failure)
    with pytest.raises(OSError, match=failure):
        if kind == "blast":
            _blast(memory).run(1)
        else:
            _radio(memory).run()
    assert memory.events[-1] == failure
    assert memory.events.count(failure) == 1
