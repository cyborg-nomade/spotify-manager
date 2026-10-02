"""Verify Queue neighborhood effects without SDK, files or runtime startup."""

from dataclasses import dataclass
from dataclasses import field
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.application.queue_recommendations import QueueRecommendations
from spotify_manager.domain.queue_candidates import LastFmSimilarArtist
from spotify_manager.domain.queue_values import ArtistSeed
from tests.support.queue_neighbors import NOW
from tests.support.queue_neighbors import SEEDS
from tests.support.queue_neighbors import WEEK


def _empty_cache() -> dict[str, object]:
    return {"entries": {}}


@dataclass
class Observations:
    """Observe ordered effects and retain accepted cache mutations on failure.

    Args:
        failure: Optional named effect that fails after observation.
        cached: Optional valid cache hit, including an empty tuple.
        trace: Ordered observed effects.
        cache: Caller-owned original cache document.
    """

    failure: str | None = None
    cached: tuple[LastFmSimilarArtist, ...] | None = None
    trace: list[str] = field(default_factory=list)
    cache: dict[str, object] = field(default_factory=_empty_cache)

    def record(self, effect: str) -> None:
        """Record an effect and optionally fail after acceptance.

        Args:
            effect: Original observed effect identifier.

        Raises:
            RuntimeError: The configured accepted effect failed.
        """
        self.trace.append(effect)
        if effect == self.failure:
            raise RuntimeError(effect)

    def load(self) -> dict[str, object]:
        """Observe cache loading.

        Returns:
            Caller-owned cache document.
        """
        self.record("load")
        return self.cache

    def previous(self) -> set[str]:
        """Observe prior additions.

        Returns:
            Fixed previous artist exclusions.
        """
        self.record("previous")
        return {"previous"}

    def lookup(self, raw: object, week: date) -> tuple[LastFmSimilarArtist, ...] | None:
        """Observe cache lookup without performing unrelated reads.

        Args:
            raw: Original unchecked entry.
            week: Original effective listening week.

        Returns:
            Configured valid hit or a miss.
        """
        assert week == WEEK
        self.record("lookup")
        return self.cached

    def remember(
        self,
        cache: dict[str, object],
        entries: dict[str, object],
        seed: ArtistSeed,
        similar: tuple[LastFmSimilarArtist, ...],
        generated_at: datetime,
    ) -> None:
        """Accept the cache mutation before observing the checkpoint.

        Args:
            cache: Caller-owned complete cache.
            entries: Caller-owned entries mapping.
            seed: Original seed metadata.
            similar: Original fetched neighbors.
            generated_at: Original effective fetch time.
        """
        assert cache is self.cache
        assert generated_at == NOW
        entries[seed.key] = similar
        self.record("save")

    def neighbors(self, seed: ArtistSeed) -> tuple[LastFmSimilarArtist, ...]:
        """Observe a neighborhood read.

        Args:
            seed: Original requested seed.

        Returns:
            One deterministic eligible candidate.
        """
        assert seed == SEEDS[0]
        self.record("read")
        return (LastFmSimilarArtist("Candidate", 1.0),)

    def clock(self) -> datetime:
        """Observe the clock before any cache read.

        Returns:
            Fixed original UTC timestamp.
        """
        self.record("clock")
        return NOW

    def week(self, now: datetime) -> date:
        """Observe local-week resolution only when needed.

        Args:
            now: Original effective UTC timestamp.

        Returns:
            Fixed original listening week.
        """
        assert now == NOW
        self.record("week")
        return WEEK

    def progress(self, current: int, total: int, status: str) -> None:
        """Observe the original per-seed progress before cache lookup.

        Args:
            current: Original completed-seed count.
            total: Original number of seeds.
            status: Original progress text.
        """
        assert (current, total, status) == (0, 1, "Last.fm neighbors: Seed A")
        self.record("progress")

    def workflow(self) -> QueueRecommendations:
        """Compose an independent application workflow.

        Returns:
            Workflow using only typed in-memory boundaries.
        """
        return QueueRecommendations(
            self, self.neighbors, self.clock, self.week, self.progress
        )


TRACE = ["clock", "week", "load", "previous", "progress", "lookup", "read", "save"]


@pytest.mark.parametrize("effect", TRACE)
def test_queue_failure_retains_original_effect_prefix(effect: str) -> None:
    """Stop at the original boundary without undoing an accepted cache write.

    Args:
        effect: Original accepted boundary that fails.
    """
    observations = Observations(failure=effect)
    with pytest.raises(RuntimeError, match=effect):
        observations.workflow().run(SEEDS[:1], set(), None, 100)
    assert observations.trace == TRACE[: TRACE.index(effect) + 1]
    if effect == "save":
        assert observations.cache["entries"] == {
            "seed-a": (LastFmSimilarArtist("Candidate", 1.0),)
        }


@pytest.mark.parametrize("cached", [(), (LastFmSimilarArtist("Previous", 1.0),)])
def test_queue_valid_cache_hit_skips_fetch_and_save(
    cached: tuple[LastFmSimilarArtist, ...],
) -> None:
    """Keep empty current-week hits valid and apply prior additions to cached data.

    Args:
        cached: Original valid cached observations.
    """
    observations = Observations(cached=cached)
    assert observations.workflow().run(SEEDS[:1], set(), WEEK, 100) == ()
    assert observations.trace == ["clock", "load", "previous", "progress", "lookup"]


def test_queue_candidate_limit_does_not_skip_cache_writes() -> None:
    """Preserve neighborhood acceptance even when the final pool is empty."""
    observations = Observations()
    assert observations.workflow().run(SEEDS[:1], set(), None, 0) == ()
    assert observations.trace == TRACE


def test_queue_success_returns_ranked_observation_after_checkpoint() -> None:
    """Return the original ranking only after all accepted effects succeed."""
    observations = Observations()
    result = observations.workflow().run(SEEDS[:1], set(), None, 1)
    assert result[0].artist == "Candidate"
    assert result[0].base_rank == 1
    assert observations.trace == TRACE


def test_queue_empty_seeds_still_observe_original_opening() -> None:
    """Keep clock, cache and previous-addition reads even with no seeds."""
    observations = Observations()
    assert observations.workflow().run((), set(), None, 100) == ()
    assert observations.trace == TRACE[:4]


def test_queue_invalid_validated_entries_raise_at_original_boundary() -> None:
    """Reject changed cache shape after loading and before prior-addition reads."""
    observations = Observations(cache={"entries": []})
    with pytest.raises(AssertionError):
        observations.workflow().run(SEEDS[:1], set(), None, 100)
    assert observations.trace == TRACE[:3]
