"""Original search, liked-observation and result projection contracts."""

from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.routines import blast_from_past as routine


def _selection(title: str) -> routine.ScrobbleSelection:
    return routine.ScrobbleSelection(
        date(2020, 1, 1),
        0,
        1,
        1,
        1,
        "top down",
        1,
        routine.Scrobble(title, "Artist", "Album", 1000),
    )


def _match(identifier: str) -> routine.SpotifyTrackMatch:
    return routine.SpotifyTrackMatch(
        identifier,
        f"spotify:track:{identifier}",
        "Song",
        ("Artist",),
        "Album",
        1,
        1.0,
        1.0,
        50,
    )


@dataclass
class ResolutionSteps:
    """Observe ordered search and one shared liked-status read.

    Args:
        failure: Operation that fails.
        events: Observed operations.
        messages: Original progress messages.
        groups: Groups supplied to liked status.
    """

    failure: str = ""
    events: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    groups: list[tuple[routine.SpotifyTrackMatch, ...]] = field(default_factory=list)

    def _step(self, event: str) -> None:
        self.events.append(event)
        if event == self.failure:
            raise OSError(event)

    def cancel(self, check: routine.CancelCheck | None) -> None:
        """Record the outer per-selection cancellation check.

        Args:
            check: Original predicate.
        """
        self._step("cancel")

    def search(
        self,
        client: Spotify,
        scrobble: routine.Scrobble,
        retry: routine.RetryCall,
        check: routine.CancelCheck | None,
    ) -> tuple[routine.SpotifyTrackMatch, ...]:
        """Observe each search in selection order.

        Args:
            client: Caller-owned Spotify client.
            scrobble: Selected original play.
            retry: Existing retry policy.
            check: Existing cancellation predicate.

        Returns:
            Shared duplicate candidate or no match.
        """
        self._step(scrobble.track)
        return () if scrobble.track == "missing" else (_match("same"),)

    def liked(
        self,
        client: Spotify,
        groups: list[tuple[routine.SpotifyTrackMatch, ...]],
        retry: routine.RetryCall,
        check: routine.CancelCheck | None,
    ) -> set[str]:
        """Observe the shared liked-status request after all searches.

        Args:
            client: Caller-owned Spotify client.
            groups: Complete ordered match groups, including empty groups.
            retry: Original retry policy.
            check: Original cancellation predicate.

        Returns:
            No liked candidates.
        """
        self._step("liked")
        self.groups = groups
        return set()


def _install(steps: ResolutionSteps, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routine, "check_cancel", steps.cancel)
    monkeypatch.setattr(routine, "search_spotify_matches", steps.search)
    monkeypatch.setattr(routine, "liked_spotify_track_ids", steps.liked)


def _resolve(
    steps: ResolutionSteps,
    selections: tuple[routine.ScrobbleSelection, ...],
    present: frozenset[str] = frozenset(),
) -> routine.SpotifySelectionResolution:
    return routine.resolve_spotify_selections(
        cast(Spotify, object()),
        selections,
        routine.PlaylistState(0, present),
        progress_callback=steps.messages.append,
    )


@pytest.mark.parametrize("present", [frozenset(), frozenset({"same"})])
def test_resolution_searches_all_before_liked_status_and_projects_duplicates(
    present: frozenset[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Existing membership precedes within-batch duplicate detection.

    Args:
        present: Observed playlist membership.
        monkeypatch: Temporary Spotify boundary substitutions.
    """
    steps = ResolutionSteps()
    _install(steps, monkeypatch)
    selections = (_selection("first"), _selection("second"), _selection("missing"))
    result = _resolve(steps, selections, present)
    assert steps.events == [
        "cancel",
        "first",
        "cancel",
        "second",
        "cancel",
        "missing",
        "liked",
    ]
    assert len(steps.groups) == 3 and steps.groups[-1] == ()
    expected = (
        ["already present", "already present", "no match"]
        if present
        else ["added", "duplicate selection", "no match"]
    )
    assert [item.action for item in result.results] == expected
    assert len(result.pending_matches) == int(not present)
    assert steps.messages == [
        "Searching Spotify track 1/3",
        "Searching Spotify track 2/3",
        "Searching Spotify track 3/3",
        "Checking liked Spotify matches",
    ]


@pytest.mark.parametrize("failure", ["first", "second", "liked"])
def test_resolution_failure_prevents_later_search_or_projection(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep search and liked-status failure order.

    Args:
        failure: Selected failing observation.
        monkeypatch: Scoped substitutions.
    """
    steps = ResolutionSteps(failure)
    _install(steps, monkeypatch)
    with pytest.raises(OSError, match=failure):
        _resolve(steps, (_selection("first"), _selection("second")))
    expected = ["cancel", "first", "cancel", "second", "liked"]
    assert steps.events == expected[: expected.index(failure) + 1]


def test_empty_selection_still_observes_liked_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the empty-input progress message and liked-reader invocation.

    Args:
        monkeypatch: Scoped substitutions.
    """
    steps = ResolutionSteps()
    _install(steps, monkeypatch)
    result = _resolve(steps, ())
    assert steps.events == ["liked"] and steps.messages == [
        "Checking liked Spotify matches"
    ]
    assert not result.results and not result.pending_matches
