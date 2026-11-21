"""Conserve every play and never map ambiguous geographic name evidence."""

from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from spotify_manager.domain.listening_origin_values import OriginCatalog
from spotify_manager.domain.listening_origin_values import OriginOptions
from spotify_manager.domain.listening_origins import get_origin_analysis
from spotify_manager.domain.listening_origins import origin_fetch_candidates
from tests.domain.test_listening_tags import lifetime
from tests.support.listening_origins import origin_metadata


def test_all_outcomes_conserve_counts_without_splitting_ambiguous_countries() -> None:
    """Each observation supports one country or a visible residual category."""
    artists = tuple(
        lifetime(name, count)
        for name, count in (
            ("Alpha", 3),
            ("Beta", 2),
            ("Empty", 4),
            ("Absent", 5),
            ("Collision", 6),
            ("Partial", 7),
            ("Missing", 8),
            ("World", 1),
            ("UK", 1),
        )
    )
    entries = (
        origin_metadata(),
        origin_metadata("Beta", ("GB", "US")),
        origin_metadata("Empty", ()),
        origin_metadata("Absent", (), "unmatched", 0),
        origin_metadata("Collision", ("US",), "ambiguous", 2),
        origin_metadata("Partial", (), "incomplete", 0),
        origin_metadata("World", ("XW",)),
        origin_metadata("UK", ("GB",)),
    )
    result = get_origin_analysis(
        artists, OriginCatalog("o1-test", entries), OriginOptions()
    )
    assert result.coverage.plays == 37 and result.coverage.artists == 9
    assert result.coverage.country_plays == 4 and result.coverage.country_artists == 2
    assert result.coverage.looked_up_artists == 8
    assert sum(item.plays for item in result.coverage.outcomes) == 37
    assert sum(item.artists for item in result.coverage.outcomes) == 9
    assert [(item.code, item.plays, item.artists) for item in result.countries] == [
        ("BR", 3, 1),
        ("GB", 1, 1),
    ]
    assert result.countries[0].share == 3 / 37
    assert result.available_countries == ("BR", "GB", "US", "XW")
    assert result.retrieved_from == result.retrieved_through == entries[0].fetched_at
    outcomes = {item.artist.name: item.evidence for item in result.items}
    assert (
        outcomes["Beta"] == "multiple_countries"
        and outcomes["Collision"] == "ambiguous"
    )
    assert outcomes["Empty"] == outcomes["World"] == "no_country"


def test_evidence_country_search_and_pagination_preserve_complete_map_totals() -> None:
    """A country search includes ambiguous candidates without mapping them."""
    artists = (lifetime("Alpha", 3), lifetime("Béta", 2), lifetime("Other", 1))
    catalog = OriginCatalog(
        "o1-test", (origin_metadata(), origin_metadata("Béta", ("US",), "ambiguous", 7))
    )
    result = get_origin_analysis(
        artists,
        catalog,
        OriginOptions(country="US", evidence="ambiguous", search="BE\u0301TA"),
    )
    assert result.total == 1 and result.items[0].artist.name == "Béta"
    assert result.items[0].candidate_count == 7 and len(result.items[0].candidates) == 5
    assert result.coverage.plays == 6 and result.countries[0].plays == 3
    absent = get_origin_analysis(artists, catalog, OriginOptions(country="CA"))
    assert not absent.items
    page = get_origin_analysis(artists, catalog, OriginOptions(page=2, limit=1))
    assert page.items[0].artist.name == "Béta" and page.total == 3
    missing = get_origin_analysis(artists, catalog, OriginOptions(evidence="missing"))
    assert missing.items[0].artist.name == "Other"
    assert not get_origin_analysis(
        artists, catalog, OriginOptions(search="absent")
    ).items


def test_empty_selection_and_freshness_boundaries_remain_explicit() -> None:
    """No plays cannot create shares; refresh skips all recent lookup outcomes."""
    now = datetime(2026, 11, 21, 10, tzinfo=UTC)
    fresh = origin_metadata()
    stale = replace(
        origin_metadata("Beta"), fetched_at=(now - timedelta(days=30)).isoformat()
    )
    catalog = OriginCatalog("o1-test", (fresh, stale))
    result = get_origin_analysis((), catalog, OriginOptions())
    assert not result.countries and not result.items and result.coverage.plays == 0
    assert result.retrieved_from is None and result.retrieved_through is None
    artists = (lifetime("Alpha", 8), lifetime("Beta", 3), lifetime("Missing", 2))
    assert [
        item.name for item in origin_fetch_candidates(artists, catalog, now, 25, False)
    ] == ["Beta", "Missing"]
    assert [
        item.name for item in origin_fetch_candidates(artists, catalog, now, 1, True)
    ] == ["Alpha"]
    assert not origin_fetch_candidates((artists[0],), catalog, now, 25, False)
