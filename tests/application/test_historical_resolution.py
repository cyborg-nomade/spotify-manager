"""Independent historical match resolution and duplicate projection contracts."""

from dataclasses import dataclass
from dataclasses import field
from datetime import date

import pytest

from spotify_manager.application.historical_resolution import HistoricalResolution
from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import ScrobbleSelection
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.history_matching import SpotifyTrackMatch


def _match(identifier: str = "same", score: float = 1.0) -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        identifier,
        f"spotify:track:{identifier}",
        "Song",
        ("Artist",),
        "Album",
        1,
        1.0,
        score,
        50,
    )


def _selection(title: str) -> ScrobbleSelection:
    return ScrobbleSelection(
        date(2020, 1, 1),
        0,
        1,
        1,
        1,
        "top down",
        1,
        Scrobble(title, "Artist", "Album", 1000),
    )


@dataclass
class ResolutionMemory:
    """Record ordered observations over typed match facts.

    Args:
        matches: Search results keyed by original play title.
        events: Ordered observations.
        groups: Match groups supplied to liked-status observation.
        messages: Original progress presentation.
        liked_ids: Live liked identities.
        failure: Observation that raises.
        cancel_at: One-based selection cancellation boundary.
        checks: Observed cancellation checks.
    """

    matches: dict[str, tuple[SpotifyTrackMatch, ...]] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    groups: list[tuple[SpotifyTrackMatch, ...]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    liked_ids: set[str] = field(default_factory=set)
    failure: str = ""
    cancel_at: int = 0
    checks: int = 0

    def _step(self, name: str) -> None:
        self.events.append(name)
        if self.failure == name:
            raise OSError(name)

    def search(self, scrobble: Scrobble) -> tuple[SpotifyTrackMatch, ...]:
        """Observe a search in original selection order.

        Args:
            scrobble: Selected original play.

        Returns:
            Search-ranked observations or an empty result.
        """
        self._step(scrobble.track)
        return self.matches.get(scrobble.track, ())

    def liked(self, groups: list[tuple[SpotifyTrackMatch, ...]]) -> set[str]:
        """Observe shared liked status after every search.

        Args:
            groups: Complete ordered match groups.

        Returns:
            Live liked identities.
        """
        self._step("liked")
        self.groups = groups
        return self.liked_ids

    def cancel(self) -> None:
        """Check cancellation before each search.

        Raises:
            BlastFromPastCancelledError: The selected check is reached.
        """
        self._step("cancel")
        self.checks += 1
        if self.checks == self.cancel_at:
            raise BlastFromPastCancelledError("cancelled")


def _workflow(memory: ResolutionMemory, threshold: float = 0.9) -> HistoricalResolution:
    return HistoricalResolution(
        memory.search, memory.liked, memory.cancel, memory.messages.append, threshold
    )


@pytest.mark.parametrize("present", [False, True])
def test_searches_precede_liked_observation_and_duplicate_projection(
    present: bool,
) -> None:
    """Existing membership takes precedence over duplicate additions.

    Args:
        present: Whether the selected identity already exists in the destination.
    """
    memory = ResolutionMemory(matches={"first": (_match(),), "second": (_match(),)})
    selections = (_selection("first"), _selection("second"), _selection("missing"))
    playlist = PlaylistState(3, frozenset({"same"}) if present else frozenset())
    result = _workflow(memory).run(selections, playlist)
    expected = (
        ["already present", "already present", "no match"]
        if present
        else ["added", "duplicate selection", "no match"]
    )
    assert [item.action for item in result.results] == expected
    assert [item.qualifying_matches for item in result.results] == [1, 1, 0]
    assert result.results[2].match is None
    assert result.pending_matches == (() if present else (_match(),))
    assert memory.events == [
        "cancel",
        "first",
        "cancel",
        "second",
        "cancel",
        "missing",
        "liked",
    ]
    assert memory.groups == [(_match(),), (_match(),), ()]
    assert result.results[0].selection is selections[0]
    assert memory.messages == [
        "Searching Spotify track 1/3",
        "Searching Spotify track 2/3",
        "Searching Spotify track 3/3",
        "Checking liked Spotify matches",
    ]


@pytest.mark.parametrize(
    "liked,threshold,accepted",
    [(False, 0.9, False), (False, 0.5, True), (True, 0.9, True)],
)
def test_album_threshold_and_liked_override_flow_into_results(
    liked: bool, threshold: float, accepted: bool
) -> None:
    """Keep rejected search matches out of qualification and pending additions.

    Args:
        liked: Observed live liked state.
        threshold: Existing album threshold.
        accepted: Whether the candidate qualifies.
    """
    memory = ResolutionMemory(
        matches={"first": (_match(score=0.5),)}, liked_ids={"same"} if liked else set()
    )
    result = _workflow(memory, threshold).run(
        (_selection("first"),), PlaylistState(0, frozenset())
    )
    assert result.results[0].qualifying_matches == int(accepted)
    assert len(result.pending_matches) == int(accepted)
    assert result.results[0].action == ("added" if accepted else "no match")
    if accepted:
        assert result.pending_matches[0].liked is liked


def test_pending_matches_follow_original_selection_order() -> None:
    """Maintain ordered unique additions independently of search identities."""
    memory = ResolutionMemory(
        matches={"first": (_match("b"),), "second": (_match("a"),)}
    )
    result = _workflow(memory).run(
        (_selection("first"), _selection("second")), PlaylistState(0, frozenset())
    )
    assert [match.spotify_id for match in result.pending_matches] == ["b", "a"]


def test_empty_selection_retains_liked_observation_and_progress() -> None:
    """Observe the liked boundary even when no searches are needed."""
    memory = ResolutionMemory()
    result = _workflow(memory).run((), PlaylistState(0, frozenset()))
    assert memory.events == ["liked"] and memory.groups == []
    assert memory.messages == ["Checking liked Spotify matches"]
    assert result.results == ()
    assert result.pending_matches == ()


@pytest.mark.parametrize("failure", ["first", "second", "liked"])
def test_search_and_liked_failures_propagate_in_original_order(failure: str) -> None:
    """Stop at the failed observation without constructing partial outcomes.

    Args:
        failure: Selected failing observation.
    """
    memory = ResolutionMemory(failure=failure)
    with pytest.raises(OSError, match=failure):
        _workflow(memory).run(
            (_selection("first"), _selection("second")), PlaylistState(0, frozenset())
        )
    expected = ["cancel", "first", "cancel", "second", "liked"]
    assert memory.events == expected[: expected.index(failure) + 1]


@pytest.mark.parametrize("check", [1, 2])
def test_cancellation_precedes_each_selection_search(check: int) -> None:
    """Suppress liked reads after cancellation between selected plays.

    Args:
        check: Selected per-search cancellation boundary.
    """
    memory = ResolutionMemory(cancel_at=check)
    with pytest.raises(BlastFromPastCancelledError):
        _workflow(memory).run(
            (_selection("first"), _selection("second")), PlaylistState(0, frozenset())
        )
    assert memory.events[-1] == "cancel" and "liked" not in memory.events
