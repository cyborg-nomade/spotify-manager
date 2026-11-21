"""Hand-calculated collection evidence, uncertainty and pagination contracts."""

from dataclasses import replace

import pytest

from spotify_manager.domain.listening_library import compare_library
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import LibraryEntry
from spotify_manager.domain.listening_library_values import LibraryOptions
from spotify_manager.domain.listening_library_values import MirrorSource
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import EntityLifetime


def history(name: str, plays: int = 10, artist: str = "Alpha") -> EntityLifetime:
    """Return one exact artist/title history identity with known selected counts."""
    return EntityLifetime(listening_identity((artist, name)), name, artist, plays, 1, 2)


def entry(name: str, identity: int = 1, artist: str = "Alpha") -> LibraryEntry:
    """Return a distinct Spotify candidate using the same conservative name rule."""
    key = listening_identity((artist, name))
    return LibraryEntry("album", key, name, artist, f"spotify:album:{identity:022d}")


def catalog(entries: tuple[LibraryEntry, ...] = ()) -> LibraryCatalog:
    """Build a complete empty-or-populated album publication."""
    source = MirrorSource(
        "album",
        "ready",
        "2026-11-20T12:00:00+00:00",
        "a" * 64,
        "fixture",
        len(entries),
        "Verified",
    )
    return LibraryCatalog("l1-" + "b" * 64, "revision", (source,), entries)


def test_disjoint_coverage_retains_plays_and_never_asserts_identity() -> None:
    rows = (history("Record", 5), history("Missing", 3), history("Ambiguous", 2))
    source = catalog((entry("Record"), entry("Ambiguous", 2), entry("Ambiguous", 3)))
    result = compare_library(rows, source, LibraryOptions())
    assert [item.status for item in result.items] == [
        "name_match",
        "unmatched",
        "ambiguous",
    ]
    assert [(item.entities, item.plays) for item in result.coverage] == [
        (1, 5),
        (1, 3),
        (1, 2),
        (0, 0),
    ]
    assert sum(item.plays for item in result.coverage) == 10
    assert result.items[2].candidate_count == 2
    assert result.library_snapshot == source.snapshot


@pytest.mark.parametrize(
    "name,artist,expected",
    [
        ("  ReCoRd ", " ALPHA ", "name_match"),
        ("Re\u0301cord", "Alpha", "name_match"),
        ("Record", "Beta", "unmatched"),
        ("Récord!", "Alpha", "unmatched"),
        ("Record (Deluxe)", "Alpha", "unmatched"),
    ],
)
def test_names_retain_accents_punctuation_editions_and_artist_context(
    name: str, artist: str, expected: str
) -> None:
    source = catalog((entry("Record"), entry("Récord", 2)))
    result = compare_library((history(name, artist=artist),), source, LibraryOptions())
    assert result.items[0].status == expected


def test_duplicates_do_not_inflate_confidence_and_candidates_are_bounded() -> None:
    candidates = [entry("Same", identity) for identity in range(8)]
    candidates.append(candidates[0])
    candidates.append(replace(candidates[0], kind="track"))
    result = compare_library(
        (history("Same"),), catalog(tuple(candidates)), LibraryOptions()
    )
    assert result.items[0].candidate_count == 8
    assert len(result.items[0].candidates) == 5
    assert result.items[0].status == "ambiguous"
    one = compare_library(
        (history("Same"),), catalog((candidates[0], candidates[0])), LibraryOptions()
    )
    assert one.items[0].status == "name_match"


@pytest.mark.parametrize("state", ["missing", "error"])
def test_unavailable_publication_never_becomes_unmatched(state: str) -> None:
    source = catalog()
    status = replace(source.sources[0], state=state)  # type: ignore[arg-type]
    result = compare_library(
        (history("Record"),), replace(source, sources=(status,)), LibraryOptions()
    )
    assert result.items[0].status == "unavailable"
    assert result.coverage[-1].entities == 1


def test_search_status_minimum_and_pages_preserve_prefilter_coverage() -> None:
    rows = (history("Zeta", 8), history("Alpha", 8), history("Low", 1))
    source = catalog((entry("Zeta"),))
    options = LibraryOptions(status="unmatched", minimum_plays=2, search="ALP", limit=1)
    result = compare_library(rows, source, options)
    assert result.total == 1 and result.items[0].history.name == "Alpha"
    assert sum(item.entities for item in result.coverage) == 2
    assert sum(item.plays for item in result.coverage) == 16
    assert compare_library(rows, source, replace(options, page=2)).items == ()
    unfiltered = compare_library(rows, source, LibraryOptions(limit=1))
    assert unfiltered.items[0].history.name == "Alpha"
    assert compare_library((), source, LibraryOptions()).total == 0
