"""Queue 3 composer routes retain original selection, cancellation and marker rules."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

import pytest

from spotify_manager.application.queue_3_composers import composer_plan
from spotify_manager.application.queue_3_composers import resolve_composer_route
from spotify_manager.application.queue_3_values import Queue3ConfigError
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


ARTIST = "Johann Sebastian Bach"
WORKS = OwnedPlaylist("works", "[CD] Johann Sebastian Bach Works", 3)
OTHER = OwnedPlaylist("other", "[CD] Johann Sebastian Bach Collection", 2)
SOURCE = playlist_track("source", studio_release("album", "Album"))


@dataclass
class RoutingMemory:
    """Observe composer selection and the separate accepted-route timestamp.

    Args:
        choice: Scripted selection response.
        failure: Optional boundary failure before acceptance.
        events: Ordered callback observations.
    """

    choice: str = "works"
    failure: str | None = None
    events: list[str] = field(default_factory=list)

    def _record(self, name: str) -> None:
        self.events.append(name)
        if name == self.failure:
            raise OSError(name)

    def choose(self, artist: str, candidates: tuple[OwnedPlaylist, ...]) -> str:
        """Record a request to disambiguate owned candidates.

        Args:
            artist: Original logical artist name.
            candidates: Original matched owned playlists.

        Returns:
            Scripted response, including cancellation or invalid values.
        """
        self._record("choice")
        assert artist == ARTIST and candidates == (WORKS, OTHER)
        return self.choice

    def now(self) -> str:
        """Record the accepted-route clock read.

        Returns:
            Fixed original-format timestamp.
        """
        self._record("clock")
        return "accepted-at"


def _resolve(
    memory: RoutingMemory,
    routes: dict[str, object],
    owned: tuple[OwnedPlaylist, ...],
) -> tuple[OwnedPlaylist | None, bool]:
    return resolve_composer_route(
        "bach",
        ARTIST,
        "source",
        "queue",
        owned,
        {"composer_routes": routes},
        memory.choose,
        memory.now,
    )


@pytest.mark.parametrize("previous", [None, False, {"playlist_id": "stale"}])
def test_no_candidates_preserve_nonrecords_but_remove_stale_routes(
    previous: object,
) -> None:
    """Original tolerant route handling does not invent a replacement without a match.

    Args:
        previous: Existing invalid or stale route value.
    """
    memory = RoutingMemory()
    routes = {"bach": previous}
    assert _resolve(memory, routes, ()) == (None, False)
    assert routes == ({} if isinstance(previous, dict) else {"bach": previous})
    assert memory.events == []


def test_valid_saved_route_is_reused_without_choice_clock_or_rewrite() -> None:
    """Saved route metadata remains unchanged when the owned playlist still matches."""
    memory = RoutingMemory()
    routes: dict[str, object] = {"bach": {"playlist_id": "other", "unknown": True}}
    assert _resolve(memory, routes, (WORKS, OTHER)) == (OTHER, False)
    assert routes == {"bach": {"playlist_id": "other", "unknown": True}}
    assert memory.events == []


@pytest.mark.parametrize("ambiguous", [False, True])
def test_new_route_records_marker_and_time_only_after_selection(
    ambiguous: bool,
) -> None:
    """A sole candidate bypasses choice, while ambiguous candidates retain selection.

    Args:
        ambiguous: Whether a second owned candidate requires a prompt.
    """
    memory = RoutingMemory()
    routes: dict[str, object] = {}
    owned = (WORKS, OTHER) if ambiguous else (WORKS,)
    assert _resolve(memory, routes, owned) == (WORKS, False)
    assert routes == {
        "bach": {
            "artist_name": ARTIST,
            "playlist_id": "works",
            "playlist_name": WORKS.name,
            "current_track_id": "source",
            "updated_at": "accepted-at",
        }
    }
    assert memory.events == (["choice", "clock"] if ambiguous else ["clock"])


def test_missing_reader_rejects_ambiguity_after_discarding_stale_route() -> None:
    """Original candidate labels remain visible in the configuration error."""
    memory = RoutingMemory()
    routes: dict[str, object] = {"bach": {"playlist_id": "stale"}}
    with pytest.raises(Queue3ConfigError) as error:
        resolve_composer_route(
            "bach",
            ARTIST,
            "source",
            "queue",
            (WORKS, OTHER),
            {"composer_routes": routes},
            None,
            memory.now,
        )
    assert (
        str(error.value)
        == f"Multiple owned playlists match {ARTIST}: {WORKS.name}, {OTHER.name}."
    )
    assert routes == {} and memory.events == []


@pytest.mark.parametrize("choice", ["quit", "missing", "__skip__"])
def test_cancel_or_invalid_choice_does_not_restore_stale_route(choice: str) -> None:
    """Queue 3 supports quit but deliberately retains no discovery-style skip token.

    Args:
        choice: Cancellation or invalid response.
    """
    memory = RoutingMemory(choice)
    routes: dict[str, object] = {"bach": {"playlist_id": "stale"}}
    if choice == "quit":
        assert _resolve(memory, routes, (WORKS, OTHER)) == (None, True)
    else:
        with pytest.raises(Queue3ConfigError, match="not an owned match"):
            _resolve(memory, routes, (WORKS, OTHER))
    assert routes == {} and memory.events == ["choice"]


@pytest.mark.parametrize("failure", ["choice", "clock"])
def test_failed_acceptance_leaves_no_new_route(failure: str) -> None:
    """A failed choice or timestamp read leaves only the accepted stale-route removal.

    Args:
        failure: Selected callback interruption.
    """
    memory = RoutingMemory(failure=failure)
    routes: dict[str, object] = {"bach": {"playlist_id": "stale"}}
    with pytest.raises(OSError, match=failure):
        _resolve(memory, routes, (WORKS, OTHER))
    assert routes == {} and memory.events[-1] == failure


@pytest.mark.parametrize(
    "tracks,action,target",
    [
        ((), "skip", None),
        ((SOURCE, SOURCE), "complete", None),
        (
            (SOURCE, SOURCE, replace(SOURCE, spotify_id="next")),
            "composer_advance",
            "next",
        ),
        (
            (
                replace(SOURCE, spotify_id="different", name="SOURCE!"),
                replace(SOURCE, spotify_id="next", name="Next"),
            ),
            "composer_advance",
            "next",
        ),
        (
            (
                replace(SOURCE, spotify_id="different"),
                replace(SOURCE, spotify_id="other"),
            ),
            "skip",
            None,
        ),
    ],
)
def test_composer_plan_preserves_mapping_and_original_target_shape(
    tracks: tuple[PlaylistTrack, ...],
    action: str,
    target: str | None,
) -> None:
    """Owned playlist progression retains duplicate and unique-title fallback rules.

    Args:
        tracks: Original works-playlist order.
        action: Expected durable action.
        target: Expected replacement identifier, when available.
    """
    plan = composer_plan(SOURCE, WORKS, tracks)
    assert plan["action"] == action and plan["evaluation"] is None
    assert plan["composer_playlist_id"] == "works"
    assert list(plan)[-3:] == [
        "composer_playlist_id",
        "composer_playlist_name",
        "reason",
    ]
    record = plan["target"]
    assert (record["spotify_id"] if isinstance(record, dict) else None) == target
    if isinstance(record, dict):
        assert record["disc_number"] == record["track_number"] == 1
