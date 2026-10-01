"""Neighborhood observation and checkpoint contracts without SDKs or files."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.application.found_art_values import FoundArtConfigError
from spotify_manager.application.recommendation_candidates import CandidateGathering
from spotify_manager.domain.recommendation_candidates import LastFmSimilarTrack
from spotify_manager.domain.recommendation_history import TrackKey
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


STAMP = datetime(2026, 7, 22, tzinfo=UTC)
WEEK = date(2026, 7, 17)


def _payload() -> dict[str, object]:
    return {"version": 1, "entries": {}}


def _seed(title: str) -> FoundArtSeed:
    return FoundArtSeed("Seed", title, ("seed", title), "recent", 10, 5, 1.0)


@dataclass
class GatherMemory:
    """Observe cache checkpoints and retain accepted updates on interruption.

    Args:
        payload: Original caller-owned cache.
        events: Ordered observations and effects.
        messages: Original progress presentation.
        cached: Decoded current-week neighborhood or a cache miss.
        logged: Previously accepted additions.
        saved_keys: Accepted cache key snapshots.
        failure: Operation that raises after observation.
        failure_at: One-based occurrence that fails.
    """

    payload: dict[str, object] = field(default_factory=_payload)
    events: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    cached: tuple[LastFmSimilarTrack, ...] | None = None
    logged: set[TrackKey] = field(default_factory=set)
    saved_keys: list[tuple[str, ...]] = field(default_factory=list)
    failure: str = ""
    failure_at: int = 1

    def _step(self, name: str) -> None:
        self.events.append(name)
        if name == self.failure and self.events.count(name) == self.failure_at:
            raise OSError(name)

    def clock(self) -> datetime:
        """Observe effective time before cache reads.

        Returns:
            Stable effective UTC timestamp.
        """
        self._step("clock")
        return STAMP

    def week(self, stamp: datetime) -> date:
        """Resolve the default week only when no week was supplied.

        Args:
            stamp: Effective UTC timestamp.

        Returns:
            Original listening week's Friday.
        """
        self._step("week")
        assert stamp is STAMP
        return WEEK

    def load(self) -> dict[str, object]:
        """Read the mutable cache.

        Returns:
            Original caller-owned payload.
        """
        self._step("load")
        return self.payload

    def previous(self) -> set[TrackKey]:
        """Observe prior accepted additions.

        Returns:
            Logged normalized identities.
        """
        self._step("previous")
        return self.logged

    def lookup(
        self, entry: object, week: date
    ) -> tuple[LastFmSimilarTrack, ...] | None:
        """Observe a current-week cache lookup.

        Args:
            entry: Original raw record, absent in these cache-miss cases.
            week: Effective listening week.

        Returns:
            Decoded current-week observation or a miss.
        """
        self._step("lookup")
        assert week == WEEK
        return self.cached

    def neighbors(self, seed: FoundArtSeed) -> tuple[LastFmSimilarTrack, ...]:
        """Observe one seed's original Last.fm neighborhood.

        Args:
            seed: Original display metadata.

        Returns:
            One shared eligible candidate.
        """
        self._step("fetch")
        return (LastFmSimilarTrack("Candidate", "Song", 1.0),)

    def remember(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: FoundArtSeed,
        similar: tuple[LastFmSimilarTrack, ...],
        generated_at: datetime,
    ) -> None:
        """Update working cache before accepting the checkpoint.

        Args:
            cache: Complete original caller-owned cache.
            entries: Original mutable entries container.
            seed: Original seed metadata.
            similar: Fetched neighbors.
            generated_at: Effective UTC timestamp.
        """
        assert cache is self.payload and generated_at is STAMP
        assert similar == (LastFmSimilarTrack("Candidate", "Song", 1.0),)
        entries["\0".join(seed.key)] = {"track": seed.track}
        self._step("save")
        self.saved_keys.append(tuple(entries))

    def progress(self, message: str) -> None:
        """Present each seed before cache lookup.

        Args:
            message: Original progress message.
        """
        self._step("progress")
        self.messages.append(message)


def _workflow(memory: GatherMemory) -> CandidateGathering:
    return CandidateGathering(
        memory, memory.neighbors, memory.clock, memory.week, memory.progress
    )


def test_each_fetch_is_checkpointed_before_aggregation_and_next_seed() -> None:
    """Keep two seed observations and cache acceptance in their original order."""
    memory = GatherMemory()
    result = _workflow(memory).run((_seed("One"), _seed("Two")), set(), WEEK, 10)
    assert memory.events == [
        "clock",
        "load",
        "previous",
        "progress",
        "lookup",
        "fetch",
        "save",
        "progress",
        "lookup",
        "fetch",
        "save",
    ]
    assert memory.saved_keys == [("seed\0One",), ("seed\0One", "seed\0Two")]
    assert memory.messages == [
        "Getting Last.fm neighbors for seed 1/2",
        "Getting Last.fm neighbors for seed 2/2",
    ]
    assert len(result) == 1 and result[0].score == 2.3
    assert result[0].supporting_seeds == ("Seed - One", "Seed - Two")


@pytest.mark.parametrize(
    "cached", [(), (LastFmSimilarTrack("Candidate", "Song", 1.0),)]
)
def test_current_week_cache_including_empty_neighborhood_skips_fetch(
    cached: tuple[LastFmSimilarTrack, ...],
) -> None:
    """Treat valid empty observations as cache hits.

    Args:
        cached: Decoded original current-week cache contents.
    """
    memory = GatherMemory(cached=cached)
    result = _workflow(memory).run((_seed("One"),), set(), WEEK, 10)
    assert memory.events == ["clock", "load", "previous", "progress", "lookup"]
    assert len(result) == len(cached) and not memory.saved_keys


def test_empty_seed_input_still_observes_clock_cache_and_previous_additions() -> None:
    """Retain the original preparation steps before returning no candidates."""
    memory = GatherMemory()
    assert _workflow(memory).run((), set(), WEEK, 10) == ()
    assert memory.events == ["clock", "load", "previous"]


def test_missing_week_is_resolved_before_cache_reads() -> None:
    """Resolve the default listening week from the effective clock timestamp."""
    memory = GatherMemory()
    _workflow(memory).run((), set(), None, 10)
    assert memory.events == ["clock", "week", "load", "previous"]


@pytest.mark.parametrize(
    "heard,logged", [({("candidate", "song")}, set()), (set(), {("candidate", "song")})]
)
def test_excluded_neighbors_are_still_checkpointed(
    heard: set[TrackKey], logged: set[TrackKey]
) -> None:
    """Cache observation is accepted before heard/logged filtering.

    Args:
        heard: Original listening exclusions.
        logged: Previously accepted additions.
    """
    memory = GatherMemory(logged=logged)
    original_heard = heard.copy()
    assert _workflow(memory).run((_seed("One"),), heard, WEEK, 10) == ()
    assert memory.saved_keys == [("seed\0One",)]
    assert heard == original_heard


@pytest.mark.parametrize("pool_size", [0, -1])
def test_invalid_pool_size_precedes_clock_and_cache_observations(
    pool_size: int,
) -> None:
    """Retain request validation before any date or cache read.

    Args:
        pool_size: Invalid candidate pool limit.
    """
    memory = GatherMemory()
    with pytest.raises(FoundArtConfigError, match="at least 1"):
        _workflow(memory).run((), set(), None, pool_size)
    assert memory.events == []


@pytest.mark.parametrize("entries", [None, [], "bad"])
def test_changed_entry_container_fails_before_prior_addition_reads(
    entries: object,
) -> None:
    """Keep the original assertion for a corrupted validated cache container.

    Args:
        entries: Invalid entries container supplied by the storage boundary.
    """
    memory = GatherMemory()
    memory.payload["entries"] = entries
    with pytest.raises(AssertionError, match="changed type"):
        _workflow(memory).run((), set(), WEEK, 10)
    assert memory.events == ["clock", "load"]


def test_missing_entries_retains_original_key_error() -> None:
    """Do not strengthen the original cache reconstruction behavior."""
    memory = GatherMemory(payload={"version": 1})
    with pytest.raises(KeyError, match="entries"):
        _workflow(memory).run((), set(), WEEK, 10)
    assert memory.events == ["clock", "load"]


@pytest.mark.parametrize(
    "failure",
    ["clock", "week", "load", "previous", "progress", "lookup", "fetch", "save"],
)
def test_observation_and_checkpoint_failures_stop_the_workflow(failure: str) -> None:
    """Keep failures at their original observation or persistence boundaries.

    Args:
        failure: Selected failure operation.
    """
    memory = GatherMemory(failure=failure)
    with pytest.raises(OSError, match=failure):
        _workflow(memory).run((_seed("One"), _seed("Two")), set(), None, 10)
    assert memory.events[-1] == failure and not memory.saved_keys


def test_second_checkpoint_failure_retains_first_accepted_cache_snapshot() -> None:
    """Preserve accepted progress and the working entry update on later failure."""
    memory = GatherMemory(failure="save", failure_at=2)
    with pytest.raises(OSError, match="save"):
        _workflow(memory).run((_seed("One"), _seed("Two")), set(), WEEK, 10)
    assert memory.saved_keys == [("seed\0One",)]
    assert memory.payload["entries"] == {
        "seed\0One": {"track": "One"},
        "seed\0Two": {"track": "Two"},
    }
    assert memory.events[-1] == "save"
