"""Freeze Queue 3 composer marker and route semantics before extraction."""

from dataclasses import replace
from typing import cast

import pytest

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.routines import queue_3
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
WORKS = OwnedPlaylist("works", "[CD] Johann Sebastian Bach Works", 3)


@pytest.mark.parametrize(
    "tracks,action,target",
    [
        ((), "skip", None),
        ((SOURCE,), "complete", None),
        ((SOURCE, SOURCE), "complete", None),
        (
            (SOURCE, SOURCE, replace(SOURCE, spotify_id="next")),
            "composer_advance",
            "next",
        ),
        (
            (replace(SOURCE, spotify_id="other", name="SOURCE!"), SOURCE),
            "complete",
            None,
        ),
        (
            (
                replace(SOURCE, spotify_id="other", name="SOURCE!"),
                replace(SOURCE, spotify_id="next", name="New"),
            ),
            "composer_advance",
            "next",
        ),
        (
            (
                replace(SOURCE, spotify_id="other"),
                replace(SOURCE, spotify_id="another"),
            ),
            "skip",
            None,
        ),
    ],
)
def test_original_composer_marker_mapping_and_duplicate_rules(
    tracks: tuple[PlaylistTrack, ...],
    action: str,
    target: str | None,
) -> None:
    """ID priority, unique title fallback and duplicate skipping retain original plans.

    Args:
        tracks: Original works-playlist marker order.
        action: Expected durable action.
        target: Expected target ID when advancement is possible.
    """
    plan = queue_3._composer_plan(SOURCE, WORKS, tracks)
    assert plan["action"] == action
    assert plan["composer_playlist_id"] == "works"
    assert plan["composer_playlist_name"] == "[CD] Johann Sebastian Bach Works"
    record = plan["target"]
    assert (record["spotify_id"] if isinstance(record, dict) else None) == target
    assert plan["evaluation"] is None


def _quit(artist_name: str, candidates: tuple[OwnedPlaylist, ...]) -> str:
    return "quit"


def _invalid(artist_name: str, candidates: tuple[OwnedPlaylist, ...]) -> str:
    return "unowned"


@pytest.mark.parametrize("choice", [None, _quit, _invalid])
def test_original_stale_route_is_removed_before_ambiguous_choice(
    choice: queue_3.ComposerPlaylistReader | None,
) -> None:
    """Cancellation and selection errors leave the stale route removed in working state.

    Args:
        choice: Missing, cancelled or invalid selection callback.
    """
    routes: dict[str, object] = {"bach": {"playlist_id": "stale"}}
    state: dict[str, object] = {"composer_routes": routes}
    owned = (WORKS, OwnedPlaylist("other", "[CD] Johann Sebastian Bach Collection", 2))
    if choice is _quit:
        assert queue_3._resolve_composer_playlist(
            "bach", "Johann Sebastian Bach", "source", "queue", owned, state, choice
        ) == (None, True)
    else:
        with pytest.raises(queue_3.Queue3ConfigError):
            queue_3._resolve_composer_playlist(
                "bach", "Johann Sebastian Bach", "source", "queue", owned, state, choice
            )
    assert routes == {}


def test_original_valid_route_reuse_leaves_original_record_unchanged() -> None:
    """Existing valid routes do not refresh marker IDs or timestamps."""
    route: dict[str, object] = {
        "playlist_id": "works",
        "current_track_id": "old",
        "unknown": True,
    }
    state: dict[str, object] = {"composer_routes": {"bach": route}}
    assert queue_3._resolve_composer_playlist(
        "bach", "Johann Sebastian Bach", "source", "queue", (WORKS,), state, None
    ) == (WORKS, False)
    assert route == {"playlist_id": "works", "current_track_id": "old", "unknown": True}


def test_original_snapshot_uses_last_valid_route_for_the_same_marker() -> None:
    """Queue 3 snapshot routing intentionally differs from discovery's first match."""
    routes: dict[str, object] = {
        "first": {"current_track_id": "source", "artist_name": "First"},
        "invalid": False,
        "missing": {"current_track_id": "source", "artist_name": ""},
        "last": {"current_track_id": "source", "artist_name": "Last"},
    }
    run = queue_3._new_run("queue", [SOURCE, SOURCE], {"composer_routes": routes})
    entries = cast(list[dict[str, object]], run["entries"])
    assert len(entries) == 1
    assert entries[0]["artist_id"] == "last" and entries[0]["artist_name"] == "Last"
    assert entries[0]["status"] == "pending" and entries[0]["plan"] is None
