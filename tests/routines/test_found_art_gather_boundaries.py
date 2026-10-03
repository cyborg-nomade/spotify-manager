"""Original recommendation cache and aggregation observation boundaries."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path

import pytest

from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.client.lastfm import LastFmSimilarTrack
from spotify_manager.infrastructure import recommendations_data as data
from spotify_manager.routines import found_art
from tests.routines.test_found_art import seed


STAMP = datetime(2026, 7, 22, tzinfo=UTC)
WEEK = date(2026, 7, 17)


@dataclass
class GatherSteps:
    """Observe cache acceptance before candidate projection.

    Args:
        failure: Boundary to fail after observation.
        events: Ordered operations.
        cached: Whether the cache supplies an empty current-week observation.
        cache: Caller-owned mutable validated cache payload.
    """

    failure: str = ""
    events: list[str] = field(default_factory=list)
    cached: bool = False
    cache: dict[str, object] = field(default_factory=dict)

    def _step(self, name: str) -> None:
        self.events.append(name)
        if self.failure == name:
            raise OSError(name)

    def load(self, path: Path) -> dict[str, object]:
        """Read the validated cache.

        Args:
            path: Original cache path.

        Returns:
            Mutable original cache payload.
        """
        self._step("load")
        self.cache = {"version": 1, "entries": {}}
        return self.cache

    def previous(
        self, path: Path, key_of: Callable[[str, str], tuple[str, str]]
    ) -> set[tuple[str, str]]:
        """Read previously added exclusions before any seed observations.

        Args:
            path: Original audit destination.

        Returns:
            Empty exclusions.
        """
        self._step("previous")
        return set()

    def lookup(
        self, entry: object, week_start: date, calendar: Callable[[datetime], date]
    ) -> tuple[LastFmSimilarTrack, ...] | None:
        """Observe a cache lookup.

        Args:
            entry: Original cache record.
            week_start: Effective listening week.

        Returns:
            An empty valid observation or a cache miss.
        """
        self._step("lookup")
        return () if self.cached else None

    def similar_tracks(
        self, artist: str, track: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarTrack, ...]:
        """Read one neighborhood on cache miss.

        Args:
            artist: Original seed artist.
            track: Original seed track.
            limit: Original request limit.

        Returns:
            One eligible candidate.
        """
        self._step("fetch")
        return (LastFmSimilarTrack("Candidate", "Song", 1.0),)

    def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Reject unrelated history observations during gathering.

        Args:
            from_timestamp: Lower bound.
            to_timestamp: Upper bound.
            limit: Page size.

        Raises:
            AssertionError: History refresh does not belong to candidate gathering.
        """
        raise AssertionError("Unexpected history refresh")

    def save(self, payload: dict[str, object], path: Path) -> None:
        """Observe the updated cache before aggregation.

        Args:
            payload: Complete updated cache.
            path: Original cache destination.
        """
        assert payload is self.cache
        assert payload["entries"]
        self._step("save")


def _install(steps: GatherSteps, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "load_cache", steps.load)
    monkeypatch.setattr(data, "previously_added_keys", steps.previous)
    monkeypatch.setattr(data, "cached_neighbors", steps.lookup)
    monkeypatch.setattr(data, "save_cache", steps.save)


def _gather(
    steps: GatherSteps, log: Path | None = Path("audit")
) -> tuple[found_art.FoundArtCandidate, ...]:
    return found_art.gather_candidates(
        steps,
        (seed("Seed", "One"), seed("Seed", "Two")),
        set(),
        log_path=log,
        week_start=WEEK,
        now=STAMP,
    )


@pytest.mark.parametrize("failure", ["load", "previous", "lookup", "fetch", "save"])
def test_candidate_observation_failure_stops_before_later_seeds(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not read another neighborhood or project results after a failed checkpoint.

    Args:
        failure: Selected failing observation or cache persistence.
        monkeypatch: Temporary integration substitutions.
    """
    steps = GatherSteps(failure)
    _install(steps, monkeypatch)
    with pytest.raises(OSError, match=failure):
        _gather(steps)
    expected = ["load", "previous", "lookup", "fetch", "save"]
    assert steps.events == expected[: expected.index(failure) + 1]


def test_each_fetched_neighborhood_is_saved_before_the_next_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain per-seed cache checkpoints and cumulative support scoring.

    Args:
        monkeypatch: Temporary integration substitutions.
    """
    steps = GatherSteps()
    _install(steps, monkeypatch)
    result = _gather(steps)
    assert steps.events == [
        "load",
        "previous",
        "lookup",
        "fetch",
        "save",
        "lookup",
        "fetch",
        "save",
    ]
    assert len(result) == 1 and result[0].score == 2.3
    assert result[0].supporting_seeds == ("Seed - One", "Seed - Two")


def test_empty_current_week_cache_skips_fetch_and_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid empty neighborhood remains cached rather than triggering another read.

    Args:
        monkeypatch: Temporary integration substitutions.
    """
    steps = GatherSteps(cached=True)
    _install(steps, monkeypatch)
    assert _gather(steps, None) == ()
    assert steps.events == ["load", "lookup", "lookup"]
