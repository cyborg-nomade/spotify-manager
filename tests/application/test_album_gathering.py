"""Independent sequential Sauvignon album observations and original input slicing."""

from dataclasses import dataclass
from dataclasses import field
from datetime import date

import pytest

from spotify_manager.application.album_recommendations import AlbumGathering
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from tests.support.album_evidence import AlbumEvidenceCase
from tests.support.album_evidence import read_case
from tests.support.album_evidence import recommendation_records


WEEK = date(2026, 8, 7)


@dataclass
class AlbumMemory:
    """Observe original progress and searches without clients or retry configuration.

    Args:
        case: Immutable original observations and exclusions.
        failure: Optional observation to fail after recording it.
        events: Ordered accepted original observations.
    """

    case: AlbumEvidenceCase
    failure: str = ""
    events: list[str] = field(default_factory=list)

    def _step(self, message: str) -> None:
        self.events.append(message)
        if self.failure == message:
            raise OSError(message)

    def search(self, candidate: FoundArtCandidate) -> tuple[SpotifyAlbumOption, ...]:
        """Read the original ordered eligible editions for one candidate.

        Args:
            candidate: Original ranked track value.

        Returns:
            Configured immutable original observations.

        Raises:
            OSError: The configured observation fails.
        """
        assert candidate in self.case.candidates
        self._step(f"search:{candidate.track}")
        return self.case.observations[candidate.track]

    def progress(self, message: str) -> None:
        """Present original progress immediately before its candidate's search.

        Args:
            message: Original visible candidate progress.

        Raises:
            OSError: The configured progress observer fails.
        """
        self._step(message)

    def run(self) -> tuple[AlbumRecommendation, ...]:
        """Compose and execute an independent original album evidence scenario.

        Returns:
            Original ranked recommendations after all observations succeed.

        Raises:
            OSError: An injected observation fails.
        """
        workflow = AlbumGathering(self.search, self.progress)
        return workflow.run(
            self.case.candidates,
            self.case.excluded,
            self.case.existing,
            self.case.maximum,
            WEEK,
        )


@pytest.mark.parametrize(
    "name", ["grouped", "duplicates", "exclusions", "negative-limit", "empty"]
)
def test_original_album_observation_and_result_snapshots(name: str) -> None:
    """Observe identical original inputs in order and retain exact serialized results.

    Args:
        name: Immutable original scenario name.
    """
    memory = AlbumMemory(read_case(name))
    result = memory.run()
    assert recommendation_records(result) == memory.case.expected
    assert memory.events == memory.case.events


@pytest.mark.parametrize(
    "failure",
    [
        "Resolving album evidence 1/2: New Artist - First",
        "search:First",
        "Resolving album evidence 2/2: New Artist - Second",
        "search:Second",
    ],
)
def test_observation_failure_stops_at_original_prefix(failure: str) -> None:
    """Stop immediately on failed progress or search without later observations.

    Args:
        failure: Original operation to fail after its observation.
    """
    case = read_case("grouped")
    memory = AlbumMemory(case, failure=failure)
    with pytest.raises(OSError, match=failure):
        memory.run()
    assert memory.events == case.events[: case.events.index(failure) + 1]


def test_all_excluded_options_still_observe_every_considered_search() -> None:
    """Destination IDs filter evidence after each read rather than skip reads."""
    case = read_case("grouped")
    for group in case.observations.values():
        case.existing.update(option.spotify_id for option in group)
    original_existing = case.existing.copy()
    memory = AlbumMemory(case)
    assert memory.run() == ()
    assert memory.events == case.events
    assert case.existing == original_existing


def test_empty_pool_has_no_progress_or_search_observations() -> None:
    """An empty candidate pool does not invent read or presentation effects."""
    case = read_case("empty")
    memory = AlbumMemory(case)
    workflow = AlbumGathering(memory.search, memory.progress)
    assert workflow.run((), set(), set(), 10, WEEK) == ()
    assert memory.events == []
