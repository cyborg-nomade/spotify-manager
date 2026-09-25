"""Decision tables for canonical editions and complete Requeue plans."""

from dataclasses import replace

import pytest

from spotify_manager.domain.discography import release_transition
from spotify_manager.domain.discography import select_editions
from spotify_manager.domain.requeue import plan_transition
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


def test_saved_edition_retains_earliest_group_chronology() -> None:
    """Select the saved edition while retaining the original release's date."""
    plain = studio_release("plain", "Debut", "2001")
    deluxe = replace(
        studio_release("deluxe", "Debut (Deluxe Edition)", "2010"),
        saved=True,
        plain=False,
        edition_rank=1,
    )
    middle = studio_release("middle", "Middle", "2005")
    actual = select_editions([middle, deluxe, plain])
    assert actual == (replace(deluxe, chronology_date="2001"), middle)


def test_empty_catalog_has_no_editions() -> None:
    """Handle an empty eligible catalog without introducing a fallback edition."""
    assert select_editions([]) == ()


def test_date_and_release_ties_keep_original_ordering() -> None:
    """Sort valid dates before unknown ones, retaining type and title tie breakers."""
    album = studio_release("a", "Alpha", "2000")
    ep = replace(studio_release("e", "Early", "2000"), release_type="EP")
    unknown = studio_release("u", "Unknown", "invalid")
    later = studio_release("z", "Zebra", "2000")
    assert select_editions([unknown, ep, later, album]) == (album, later, ep, unknown)


@pytest.mark.parametrize(
    ("source", "current_id", "next_id"),
    [
        ("First (Deluxe Edition)", "first", "second"),
        ("Second", "second", None),
        ("Absent", None, None),
    ],
)
def test_release_transition_uses_canonical_identity(
    source: str, current_id: str | None, next_id: str | None
) -> None:
    """Find the first canonical match and its immediate successor.

    Args:
        source: Original source release title.
        current_id: Expected canonical identifier, or None.
        next_id: Expected successor identifier, or None.
    """
    releases = (studio_release("first", "First"), studio_release("second", "Second"))
    current, following = release_transition(source, releases)
    assert (current.spotify_id if current else None) == current_id
    assert (following.spotify_id if following else None) == next_id


@pytest.mark.parametrize(
    ("present", "has_current", "has_next", "has_tracks", "action"),
    [
        (False, True, True, True, "advance"),
        (True, True, True, True, "advance"),
        (False, False, True, True, "skip"),
        (False, True, False, False, "drop"),
        (False, True, True, False, "skip"),
    ],
)
def test_transition_plan_decision_table(
    present: bool, has_current: bool, has_next: bool, has_tracks: bool, action: str
) -> None:
    """Preserve the source, successor, and duplicate rules without I/O.

    Args:
        present: Whether the replacement already appears in the playlist.
        has_current: Whether the source release is eligible.
        has_next: Whether a successor exists.
        has_tracks: Whether the successor has playable tracks.
        action: Expected transition kind.
    """
    current, following = studio_release("one", "One"), studio_release("two", "Two")
    source, target = playlist_track("source", current), release_track("target")
    playlist = (source, playlist_track("target", following)) if present else (source,)
    plan = plan_transition(
        playlist,
        current if has_current else None,
        following if has_next else None,
        (target,) if has_tracks else (),
    )
    assert plan.action == action
    assert plan.source is source
    assert plan.before == len(playlist)
    assert plan.already_present == (present and action == "advance")


def test_empty_playlist_plan_is_a_noop() -> None:
    """Return the unchanged empty-playlist action and counts."""
    plan = plan_transition((), None, None, ())
    assert (plan.action, plan.before, plan.after, plan.reason) == (
        "empty",
        0,
        0,
        "playlist is empty",
    )
