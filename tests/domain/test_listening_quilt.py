"""Keep ranked albums, missing images and all selected listening counts explicit."""

from datetime import UTC
from datetime import datetime

from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.domain.listening_cover_values import QuiltOptions
from spotify_manager.domain.listening_quilt import cover_fetch_candidates
from spotify_manager.domain.listening_quilt import get_quilt_analysis
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import ListeningCounts
from tests.support.listening_covers import album
from tests.support.listening_covers import cover_result


def lifetime(name: str, plays: int = 2, artist: str = "Alpha") -> EntityLifetime:
    """Preserve exact album/artist identities in simple hand-counted histories.

    Args:
        name: Synthetic original album title.
        plays: Hand-counted recorded plays.
        artist: Synthetic complete credited artist name.

    Returns:
        One hand-counted album history with its artist context.
    """
    return EntityLifetime(album(name, artist).key, name, artist, plays, 0, 1000)


def counts(plays: int, missing: int = 1) -> ListeningCounts:
    """Keep whole-selection missing-album rows outside named album lifetimes.

    Args:
        plays: Hand-counted recorded plays.
        missing: Selected plays without album names.

    Returns:
        Whole-selection counts including missing album names.
    """
    return ListeningCounts(plays, 1, 6, 6, 2, missing, 0, 1000)


def test_all_outcomes_reconcile_visible_plays_without_hiding_missing_art() -> None:
    """Every artwork outcome keeps its album rank; unknown albums remain residual."""
    entries = (
        cover_result("Ready"),
        cover_result("Absent", state="no_cover"),
        cover_result("Unmatched", state="unmatched", count=0),
        cover_result("Ambiguous", state="ambiguous", count=7),
        cover_result("Partial", state="incomplete", count=0),
    )
    lifetimes = tuple(
        lifetime(name)
        for name in ("Ready", "Absent", "Unmatched", "Ambiguous", "Partial", "Missing")
    )
    catalog = CoverCatalog("c1-fixture", tuple(item.metadata for item in entries))
    data = get_quilt_analysis(lifetimes, counts(13), catalog, QuiltOptions(9))
    assert len(data.items) == 6 and data.coverage.shown_plays == 12
    assert sum(item.plays for item in data.coverage.outcomes) == 12
    assert sum(item.albums for item in data.coverage.outcomes) == 6
    assert data.coverage.artwork_albums == 1 and data.coverage.artwork_plays == 2
    assert data.coverage.album_plays + data.coverage.missing_album_plays == 13
    assert all(item.album.share == 1 / 6 for item in data.items)
    assert data.items[0].album.name == "Absent"
    assert (
        data.retrieved_from == data.retrieved_through == entries[0].metadata.fetched_at
    )
    ambiguous = next(item for item in data.items if item.album.name == "Ambiguous")
    assert ambiguous.candidate_count == 7 and len(ambiguous.candidates) == 5


def test_search_size_and_artist_context_never_merge_edition_identities() -> None:
    """Album/artist search preserves accents, title punctuation and edition labels."""
    lifetimes = (
        lifetime("Béta", 5),
        lifetime("Béta", 4, "Other"),
        lifetime("Béta (Deluxe)", 3),
    )
    data = get_quilt_analysis(
        lifetimes,
        counts(13),
        CoverCatalog("c1-empty", ()),
        QuiltOptions(9, "BE\u0301TA"),
    )
    assert len(data.items) == 3 and len({item.album.key for item in data.items}) == 3
    assert [item.album.plays for item in data.items] == [5, 4, 3]
    artist = get_quilt_analysis(
        lifetimes, counts(13), CoverCatalog("c1-empty", ()), QuiltOptions(9, "Other")
    )
    assert len(artist.items) == 1 and artist.coverage.shown_plays == 4
    assert artist.coverage.album_plays == 12 and artist.coverage.albums == 3
    many = tuple(lifetime(str(index), index + 1) for index in range(20))
    limited = get_quilt_analysis(
        many, counts(211), CoverCatalog("c1-empty", ()), QuiltOptions(9)
    )
    assert len(limited.items) == 9 and limited.items[0].album.plays == 20
    assert (
        limited.coverage.matching_albums == 20 and limited.coverage.shown_plays == 144
    )


def test_empty_and_freshness_boundaries_preserve_explicit_lookup_scope() -> None:
    """Only visible missing/stale titles are eligible; force never expands the quilt."""
    empty = get_quilt_analysis(
        (), counts(0, 0), CoverCatalog("c1-empty", ()), QuiltOptions()
    )
    assert empty.items == () and empty.retrieved_from is None
    stale = cover_result("Old", fetched_at="2026-10-23T10:00:00+00:00").metadata
    fresh = cover_result("Fresh").metadata
    data = get_quilt_analysis(
        (lifetime("Old", 5), lifetime("Fresh", 4), lifetime("Missing", 3)),
        counts(13),
        CoverCatalog("c1-fixture", (stale, fresh)),
        QuiltOptions(9),
    )
    now = datetime(2026, 11, 22, 10, tzinfo=UTC)
    assert [
        item.name for item in cover_fetch_candidates(data.items, now, 10, False)
    ] == ["Old", "Missing"]
    assert [
        item.name for item in cover_fetch_candidates(data.items, now, 1, False)
    ] == ["Old"]
    assert [
        item.name for item in cover_fetch_candidates(data.items, now, 10, True)
    ] == ["Old", "Fresh", "Missing"]
    assert cover_fetch_candidates((), now, 10, False) == ()
    absent = get_quilt_analysis(
        (lifetime("Present"),),
        counts(3),
        CoverCatalog("c1-empty", ()),
        QuiltOptions(9, "absent"),
    )
    assert absent.items == () and absent.coverage.matching_albums == 0
