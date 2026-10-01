"""Protect Palace positions, saved editions and classifications without SDKs."""

from dataclasses import dataclass
from dataclasses import replace

import pytest

from spotify_manager.domain.palace_albums import alphabetical
from spotify_manager.domain.palace_albums import classify
from spotify_manager.domain.palace_albums import cursor_index
from spotify_manager.domain.palace_albums import preferred_catalog
from spotify_manager.domain.palace_albums import preferred_saved
from spotify_manager.domain.palace_values import CatalogAlbum
from spotify_manager.domain.palace_values import PalaceAlbumResult
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack


@dataclass(frozen=True)
class SavedFacts:
    """Supply original saved identity and labels without boundary model imports.

    Args:
        artist: Original artist spelling.
        album: Original album title.
        uri: Original album reference.
        spotify_id: Original parsed identity.
    """

    artist: str
    album: str
    uri: str
    spotify_id: str


FIRST = SavedFacts("Artist", "Release", "album:first", "first")
SECOND = SavedFacts("Artist", "Release", "album:second", "second")
MAPPED = SpotifyAlbum("first", "album:first", "Artist", "Release", True, 1.0)
TRACK = SpotifyFirstTrack("one", "track:one", "First")
PROPOSAL = PalaceAlbumResult(
    "alphabetical", "Artist", "Release", MAPPED, TRACK, "added"
)


@pytest.mark.parametrize(
    "start,identities",
    [
        (0, ("first", "second")),
        (1, ("second", "first")),
        (-1, ("second", "first")),
        (9, ("second", "first")),
    ],
)
def test_palace_alphabetical_wraps_original_positions(
    start: int,
    identities: tuple[str, ...],
) -> None:
    """Keep original full mirror facts across supported wrapping positions.

    Args:
        start: Original starting position.
        identities: Original ordered expected identities.
    """
    selected = alphabetical((FIRST, SECOND), start, 2)
    assert tuple(album.spotify_id for album in selected) == identities


@pytest.mark.parametrize("count", [-1, 0, 3])
def test_palace_alphabetical_requires_original_count_within_mirror(count: int) -> None:
    """Protect count boundaries before any modulo or lookup.

    Args:
        count: Original invalid selection size.
    """
    with pytest.raises(ValueError, match="count must fit"):
        alphabetical((FIRST, SECOND), 0, count)


@pytest.mark.parametrize(
    "last,fallback,expected",
    [("", 0, 0), ("", 9, 1), ("absent", 3, 1), ("first", 0, 1), ("second", 1, 0)],
)
def test_palace_cursor_prefers_original_identity_and_wraps_fallback(
    last: str,
    fallback: int,
    expected: int,
) -> None:
    """Retain current mirror identity authority over stale numeric cursor positions.

    Args:
        last: Original last selected identity.
        fallback: Original validated fallback position.
        expected: Original next current-mirror position.
    """
    assert cursor_index((FIRST, SECOND), last, fallback) == expected


def test_palace_saved_edition_prefers_best_match_and_keeps_first_ties() -> None:
    """Retain exact normalized artist qualification and stable edition preference."""
    other = SavedFacts("Other", "Release", "album:other", "other")
    fuzzy = SavedFacts("Artist", "Releas", "album:fuzzy", "fuzzy")
    assert (
        preferred_saved(" ARTIST ", "Release", (other, fuzzy, FIRST, SECOND)) == MAPPED
    )
    assert preferred_saved("Artist", "Release", (FIRST,), 1.1) is None
    assert preferred_saved("Missing", "Release", (FIRST,)) is None
    assert preferred_saved("Artist", "Release", ()) is None


def test_palace_classification_preserves_missing_live_and_pending_order() -> None:
    """Retain no-match precedence and the original first distinct pending marker."""
    missing_album = replace(PROPOSAL, spotify_album=None)
    missing_track = replace(PROPOSAL, first_track=None)
    results, pending = classify(
        [missing_album, missing_track, PROPOSAL, PROPOSAL], frozenset()
    )
    assert tuple(result.action for result in results) == (
        "no match",
        "no match",
        "added",
        "duplicate selection",
    )
    assert pending == (TRACK,)
    results, pending = classify([PROPOSAL], frozenset({"one"}))
    assert results[0].action == "already present"
    assert pending == ()
    assert classify([], frozenset()) == ((), ())


def test_palace_catalog_qualifies_any_credit_and_preserves_rank() -> None:
    """Keep primary display names when qualifying the requested secondary artist."""
    wrong = CatalogAlbum("wrong", "album:wrong", "Release", ("Other",), 1)
    fuzzy = CatalogAlbum("fuzzy", "album:fuzzy", "Releas", ("Artist",), 2)
    exact = CatalogAlbum("exact", "album:exact", "Release", ("Other", "Artist"), 4)
    tied = CatalogAlbum("tied", "album:tied", "Release", ("Artist",), 3)
    result = preferred_catalog(" Artist ", "Release", (wrong, fuzzy, exact, tied))
    assert result == SpotifyAlbum("tied", "album:tied", "Artist", "Release", False, 1.0)
    secondary = preferred_catalog("Artist", "Release", (exact,))
    assert secondary is not None and secondary.artist == "Other"
    assert preferred_catalog("Artist", "Release", (exact,), 1.1) is None
    assert preferred_catalog("Artist", "Release", (wrong,)) is None
