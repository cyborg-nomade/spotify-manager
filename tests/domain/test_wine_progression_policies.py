"""New Wine preserves its exact-ID and plain-title progression rules."""

from dataclasses import replace

import pytest

from spotify_manager.domain.new_wine import selected_transition
from spotify_manager.domain.new_wine import track_index
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
ALBUM = SOURCE.release
FOLLOWUP = playlist_track("other", studio_release("other", "Other")).release
TARGET = release_track("target")


def test_mapping_prefers_ids_and_requires_unique_plain_titles() -> None:
    """Whitespace/case normalize, while edition suffixes remain significant."""
    title = replace(TARGET, name=" SOURCE ")
    exact = release_track("source")
    assert track_index((title, exact), SOURCE) == 1
    assert track_index((TARGET, title), SOURCE) == 1
    assert track_index((title, title), SOURCE) is None
    assert track_index((replace(title, name="source (Remastered)"),), SOURCE) is None
    assert track_index((), SOURCE) is None


@pytest.mark.parametrize("release_type", ["Album", "EP", "Single"])
def test_last_track_routes_albums_and_completes_singles(release_type: str) -> None:
    """Album-like completion routes the first marker; singles have no replacement.

    Args:
        release_type: Existing release classification.
    """
    release = replace(ALBUM, release_type=release_type)
    action, target = selected_transition(SOURCE, release, (release_track("source"),))
    assert action == ("complete single" if release_type == "Single" else "sauvignon")
    assert target == (None if release_type == "Single" else release_track("source"))


def test_selected_release_switch_and_unmapped_marker_start_at_first_track() -> None:
    """Selection changes take precedence over a coincidentally matching source ID."""
    tracks = (release_track("source"), TARGET)
    assert selected_transition(SOURCE, ALBUM, tracks) == ("advance", TARGET)
    assert selected_transition(SOURCE, FOLLOWUP, tracks) == ("advance", tracks[0])
    assert selected_transition(SOURCE, ALBUM, (TARGET,)) == ("advance", TARGET)
    with pytest.raises(IndexError):
        selected_transition(SOURCE, ALBUM, ())
