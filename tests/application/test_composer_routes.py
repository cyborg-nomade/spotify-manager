"""Owned composer routes preserve stale-state mutation, choices and clock boundaries."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime

import pytest

from spotify_manager.application.composer_routes import ChoiceCandidate
from spotify_manager.application.composer_routes import resolve_composer_route
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.composers import OwnedPlaylist


FIRST = OwnedPlaylist("first", "[CD] Bach works", 20)
SECOND = OwnedPlaylist("second", "[CD] Bach complete works", 40)
NOW = datetime(2026, 9, 27, tzinfo=UTC)


@dataclass
class Interaction:
    """Record choices and timestamp reads without external dependencies.

    Args:
        choice: Scripted operator response.
        events: Ordered interaction observations.
    """

    choice: str = "first"
    events: list[tuple[str, object]] = field(default_factory=list)

    def choose(self, artist: str, candidates: tuple[ChoiceCandidate, ...]) -> str:
        """Read the operator response.

        Args:
            artist: Logical composer display name.
            candidates: Original eligible works playlists.

        Returns:
            Scripted response.
        """
        self.events.append(("choice", (artist, candidates)))
        return self.choice

    def clock(self) -> datetime:
        """Record the route-acceptance clock boundary.

        Returns:
            Fixed UTC instant.
        """
        self.events.append(("clock", None))
        return NOW


def _resolve(
    state: dict[str, object],
    interaction: Interaction,
    playlists: tuple[OwnedPlaylist, ...] = (FIRST, SECOND),
    excluded: frozenset[str] = frozenset(),
) -> tuple[OwnedPlaylist | None, str | None]:
    return resolve_composer_route(
        state,
        "composer",
        "Bach",
        "source",
        playlists,
        excluded,
        interaction.choose,
        interaction.clock,
    )


@pytest.mark.parametrize("raw", [None, [], 1])
def test_route_container_is_validated_before_interaction(raw: object) -> None:
    """Malformed state retains the existing error boundary.

    Args:
        raw: Invalid saved route container.
    """
    interaction = Interaction()
    with pytest.raises(NewKidsStateError, match="composer-route"):
        _resolve({"composer_routes": raw}, interaction)
    assert interaction.events == []


def test_existing_valid_route_does_not_update_marker_timestamp_or_prompt() -> None:
    """A valid persisted selection remains byte-for-byte untouched in memory."""
    route = {
        "playlist_id": "second",
        "current_track_id": "previous",
        "updated_at": "old",
        "unknown": True,
    }
    state: dict[str, object] = {"composer_routes": {"composer": route}}
    interaction = Interaction()
    assert _resolve(state, interaction) == (SECOND, None)
    assert interaction.events == []
    assert route == {
        "playlist_id": "second",
        "current_track_id": "previous",
        "updated_at": "old",
        "unknown": True,
    }


@pytest.mark.parametrize("choice", ["__skip__", "__quit__"])
def test_stale_route_is_removed_before_skip_or_quit(choice: str) -> None:
    """Control responses do not restore the stale route or read the clock.

    Args:
        choice: Operator control response.
    """
    routes: dict[str, object] = {"composer": {"playlist_id": "stale"}}
    interaction = Interaction(choice)
    assert _resolve({"composer_routes": routes}, interaction) == (None, choice)
    assert routes == {}
    assert interaction.events == [("choice", ("Bach", (FIRST, SECOND)))]


def test_unavailable_choice_retains_stale_route_removal() -> None:
    """Selection failure does not undo the original in-memory cleanup."""
    routes: dict[str, object] = {"composer": {"playlist_id": "stale"}}
    interaction = Interaction("missing")
    with pytest.raises(NewKidsError, match="not available"):
        _resolve({"composer_routes": routes}, interaction)
    assert routes == {} and len(interaction.events) == 1


@pytest.mark.parametrize("existing", [None, "invalid", {"playlist_id": "stale"}])
def test_single_candidate_is_accepted_without_prompt(existing: object) -> None:
    """Only new acceptance updates marker metadata and reads the clock.

    Args:
        existing: Missing, malformed or stale saved route.
    """
    routes: dict[str, object] = {"composer": existing}
    interaction = Interaction()
    assert _resolve({"composer_routes": routes}, interaction, (FIRST,)) == (FIRST, None)
    assert routes["composer"] == {
        "artist_name": "Bach",
        "playlist_id": "first",
        "playlist_name": FIRST.name,
        "current_track_id": "source",
        "updated_at": NOW.isoformat(),
    }
    assert interaction.events == [("clock", None)]


def test_multiple_candidates_persist_the_explicit_selection() -> None:
    """Operator order is preserved and acceptance happens after the selection."""
    routes: dict[str, object] = {}
    interaction = Interaction("second")
    assert _resolve({"composer_routes": routes}, interaction) == (SECOND, None)
    assert interaction.events == [
        ("choice", ("Bach", (FIRST, SECOND))),
        ("clock", None),
    ]
    assert routes["composer"] == {
        "artist_name": "Bach",
        "playlist_id": "second",
        "playlist_name": SECOND.name,
        "current_track_id": "source",
        "updated_at": NOW.isoformat(),
    }


def test_excluded_routes_are_removed_when_no_eligible_playlist_remains() -> None:
    """A formerly valid review-queue route cannot survive exclusion."""
    routes: dict[str, object] = {"composer": {"playlist_id": "first"}}
    interaction = Interaction()
    assert _resolve(
        {"composer_routes": routes}, interaction, (FIRST,), frozenset({"first"})
    ) == (None, None)
    assert routes == {} and interaction.events == []
