"""Annual import selects exact yearly names and first primary-artist markers."""

from dataclasses import replace

import pytest

from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.queue_3_import import select_import
from spotify_manager.domain.queue_3_import import yearly_playlist_ids
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


@pytest.mark.parametrize(
    "name,matches",
    [
        ("Great Discoveries 2025", True),
        ("GREAT DISCOVERIES 2025", True),
        (" Great Discoveries 2025", False),
        ("Great Discoveries 2025 ", False),
        ("Great Discoveries 2024", False),
        ("Great  Discoveries 2025", False),
    ],
)
def test_yearly_names_require_exact_casefolded_match(name: str, matches: bool) -> None:
    """Whitespace and year changes retain their original significance.

    Args:
        name: Observed source title.
        matches: Whether this exact title is accepted.
    """
    playlists = (OwnedPlaylist("id", name, 0),)
    assert yearly_playlist_ids(playlists, 2025) == (("id",) if matches else ())


def test_yearly_matches_deduplicate_ids_without_reordering_or_validation() -> None:
    """Duplicate observations and empty IDs retain the original dictionary behavior."""
    title = "Great Discoveries 2025"
    playlists = tuple(OwnedPlaylist(value, title, 0) for value in ("b", "a", "b", ""))
    assert yearly_playlist_ids(playlists, 2025) == ("b", "a", "")
    assert yearly_playlist_ids((), 2025) == ()


def test_import_uses_first_primary_credit_without_track_id_deduplication() -> None:
    """Distinct artists retain identical track IDs; duplicate artists collapse."""
    first = playlist_track("same-id", studio_release("album", "Album"))
    existing = replace(first, primary_artist_id="existing")
    duplicate = replace(first, spotify_id="later")
    other = replace(first, primary_artist_id="other")
    selection = select_import([existing], [existing, first, duplicate, other])
    assert selection.considered == (existing, first, other)
    assert selection.additions == (first, other)
    assert select_import([], []).considered == ()
