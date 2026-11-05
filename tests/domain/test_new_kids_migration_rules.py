"""Current-release position and explicit track-resolution rules."""

from dataclasses import replace

import pytest

from spotify_manager.domain.new_kids_migration import current_track_matches
from spotify_manager.domain.new_kids_migration import migration_position
from spotify_manager.domain.new_kids_plans import ReleasePlan
from tests.support.discovery_values import release
from tests.support.discovery_values import track


def test_current_release_keeps_its_chosen_position() -> None:
    """Earlier entries are acknowledged without reordering the selected releases."""
    plan = ReleasePlan(tuple(release(key) for key in ("old", "current", "next")))
    assert migration_position(plan, "current").position == 1
    with pytest.raises(ValueError, match="current album"):
        migration_position(plan, "missing")


@pytest.mark.parametrize(
    "identity,name,confirmed,expected",
    [
        ("id", "different", False, True),
        ("missing", "Title", False, False),
        ("missing", "Title", True, True),
        ("missing", "Other", True, False),
        ("missing", "", True, False),
    ],
)
def test_track_resolution(
    identity: str, name: str, confirmed: bool, expected: bool
) -> None:
    """Only exact IDs or explicitly confirmed unique titles can resume.

    Args:
        identity: Playlist marker ID.
        name: Playlist marker title.
        confirmed: Explicit current-edition confirmation.
        expected: Whether the edition identifies this marker.
    """
    tracks = (replace(track("id"), name="Title"),)
    assert current_track_matches(tracks, identity, name, confirmed) is expected


def test_duplicate_track_titles_cannot_be_resolved_by_confirmation_alone() -> None:
    """A title ambiguity still requires an edition with exact track membership."""
    tracks = (replace(track("one"), name="Title"), replace(track("two"), name="Title"))
    assert not current_track_matches(tracks, "missing", "Title", True)
