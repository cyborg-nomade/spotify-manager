"""Independent recommendation observation batches and projection boundaries."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application.recommendation_resolution import (
    RecommendationResolution,
)
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_matching import RecommendationSelection


EMPTY = PlaylistState(0, frozenset())
type Group = tuple[SpotifyTrackMatch, ...]
type Event = tuple[str, str | tuple[Group, ...]]


def _candidate(artist: str, title: str) -> FoundArtCandidate:
    return FoundArtCandidate(artist, title, (artist, title), 1, 1, ())


def _match(identity: str) -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        identity, identity, "Song", ("Artist",), "Album", 1, 1, None, 50
    )


@dataclass
class BatchMemory:
    """Observe search and liked callbacks without clients or runtime configuration.

    Args:
        groups: Configured ordered matches per original candidate title.
        liked_ids: Original live liked identities.
        failure: Optional observation to fail.
        events: Ordered accepted observations.
        messages: Original progress messages.
    """

    groups: dict[str, Group] = field(default_factory=dict)
    liked_ids: set[str] = field(default_factory=set)
    failure: str = ""
    events: list[Event] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def search(self, play: Scrobble) -> Group:
        """Read one album-free candidate search.

        Args:
            play: Original candidate search metadata.

        Returns:
            Ordered configured matches.

        Raises:
            OSError: The configured observation fails.
        """
        assert play.album == "" and play.timestamp_ms == 0
        self.events.append(("search", play.track))
        if self.failure == play.track:
            raise OSError(play.track)
        return self.groups.get(play.track, ())

    def liked(self, groups: list[Group]) -> set[str]:
        """Read liked status after the complete batch.

        Args:
            groups: Original ordered groups, including skipped searches.

        Returns:
            Configured live liked identities.

        Raises:
            OSError: The configured observation fails.
        """
        self.events.append(("liked", tuple(groups)))
        if self.failure == "liked":
            raise OSError("liked")
        return self.liked_ids

    def workflow(
        self, batch_size: int = 3, multiplier: int = 10
    ) -> RecommendationResolution:
        """Compose an isolated batch workflow.

        Args:
            batch_size: Original batch-size configuration.
            multiplier: Original maximum-candidate configuration.

        Returns:
            An independent injected workflow.
        """
        return RecommendationResolution(
            self.search, self.liked, self.messages.append, batch_size, multiplier
        )


@pytest.mark.parametrize("dry_run", [False, True])
def test_first_batch_is_fully_searched_and_later_batch_stops_at_capacity(
    dry_run: bool,
) -> None:
    """Observe a full batch before selecting one artist and stop before the next read.

    Args:
        dry_run: Original presentation mode.
    """
    memory = BatchMemory({"one": (_match("one"),), "two": (_match("two"),)})
    candidates = (
        _candidate("same", "one"),
        _candidate("same", "two"),
        _candidate("missing", "missing"),
        _candidate("later", "later"),
    )
    results, pending = memory.workflow().run(candidates, EMPTY, 1, dry_run)
    assert [result.action for result in results] == [
        "would add" if dry_run else "added",
        "artist already selected",
        "no Spotify match",
    ]
    assert pending == (_match("one"),)
    assert memory.events == [
        ("search", "one"),
        ("search", "two"),
        ("search", "missing"),
        ("liked", ((_match("one"),), (_match("two"),), ())),
    ]
    assert memory.messages == [
        "Searching Spotify candidate 1/4",
        "Searching Spotify candidate 2/4",
        "Searching Spotify candidate 3/4",
        "Checking candidates against Spotify Liked Songs",
    ]


def test_prior_artist_skips_search_and_retains_empty_liked_group() -> None:
    """Later batches omit known artists while still observing liked status once."""
    memory = BatchMemory({"one": (_match("one"),), "other": (_match("other"),)})
    candidates = (
        _candidate("same", "one"),
        _candidate("same", "two"),
        _candidate("other", "other"),
    )
    results, pending = memory.workflow(batch_size=1).run(candidates, EMPTY, 2, False)
    assert [result.action for result in results] == [
        "added",
        "artist already selected",
        "added",
    ]
    assert pending == (_match("one"), _match("other"))
    assert memory.events[2] == ("liked", ((),))
    assert ("search", "two") not in memory.events


def test_capacity_break_omits_next_eligible_and_remaining_batch_results() -> None:
    """Keep skipped outcomes until the next eligible addition breaks projection."""
    memory = BatchMemory(
        {
            "one": (_match("one"),),
            "stop": (_match("stop"),),
            "later": (_match("later"),),
        }
    )
    candidates = (
        _candidate("one", "one"),
        _candidate("stop", "stop"),
        _candidate("later", "later"),
    )
    results, pending = memory.workflow().run(candidates, EMPTY, 1, False)
    assert len(results) == 1 and pending == (_match("one"),)
    assert memory.events[:-1] == [
        ("search", "one"),
        ("search", "stop"),
        ("search", "later"),
    ]


def test_existing_key_skips_search_but_entire_empty_batch_reads_liked_status() -> None:
    """Destination-key exclusions produce empty groups without skipping liked reads."""
    memory = BatchMemory()
    item = _candidate("artist", "song")
    results, pending = memory.workflow().run(
        (item,), PlaylistState(1, frozenset(), frozenset({item.key})), 1, False
    )
    assert results[0].action == "already present" and pending == ()
    assert memory.events == [("liked", ((),))]
    assert memory.messages == ["Checking candidates against Spotify Liked Songs"]


@pytest.mark.parametrize("count", [0, -1])
def test_nonpositive_helper_count_keeps_original_empty_tolerance(count: int) -> None:
    """Helper inputs do not inherit full-run validation.

    Args:
        count: Original nonpositive request.
    """
    memory = BatchMemory()
    assert memory.workflow().run(
        (_candidate("artist", "song"),), EMPTY, count, False
    ) == ((), ())
    assert memory.events == []
    assert memory.messages == []


def test_empty_pool_does_not_read_liked_status() -> None:
    """No candidate batches means no catalog or live-status observations."""
    memory = BatchMemory()
    assert memory.workflow().run((), EMPTY, 1, False) == ((), ())
    assert memory.events == []


@pytest.mark.parametrize("failure", ["two", "liked"])
def test_failed_batch_observation_has_no_returned_projection(failure: str) -> None:
    """Search and liked exceptions propagate after their accepted observation prefix.

    Args:
        failure: Original observation to fail.
    """
    memory = BatchMemory(failure=failure)
    candidates = (_candidate("one", "one"), _candidate("two", "two"))
    with pytest.raises(OSError, match=failure):
        memory.workflow().run(candidates, EMPTY, 1, False)
    assert memory.events[:2] == [("search", "one"), ("search", "two")]
    assert len(memory.events) == (3 if failure == "liked" else 2)


def test_final_slice_preserves_candidates_beyond_nondivisible_maximum() -> None:
    """Configured search maxima limit batch starts rather than truncate final slices."""
    memory = BatchMemory()
    candidates = tuple(_candidate(str(index), str(index)) for index in range(5))
    results, pending = memory.workflow(multiplier=1).run(candidates, EMPTY, 4, False)
    assert len(results) == 5 and pending == ()
    assert memory.messages[-2] == "Searching Spotify candidate 5/4"


def test_zero_batch_size_retains_original_range_error_before_observations() -> None:
    """Invalid mutable batch configuration keeps the original error boundary."""
    memory = BatchMemory()
    with pytest.raises(ValueError, match="range"):
        memory.workflow(batch_size=0).run(
            (_candidate("artist", "song"),), EMPTY, 1, False
        )
    assert memory.events == []


def test_projection_requires_one_group_per_candidate() -> None:
    """Retain strict zip protection against corrupted batch observations."""
    memory = BatchMemory()
    with pytest.raises(ValueError, match="zip"):
        memory.workflow()._project(
            (_candidate("artist", "song"),),
            [],
            set(),
            RecommendationSelection(EMPTY, 1, False),
        )
