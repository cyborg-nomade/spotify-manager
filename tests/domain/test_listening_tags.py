"""Hand-calculated tag allocation, unknown coverage and evidence contracts."""

from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime

from spotify_manager.domain.listening_tag_values import TagCatalog
from spotify_manager.domain.listening_tag_values import TagOptions
from spotify_manager.domain.listening_tags import analyze_tags
from spotify_manager.domain.listening_tags import present_tags
from spotify_manager.domain.listening_tags import tag_fetch_candidates
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import ListeningQuery
from tests.support.listening import timestamp
from tests.support.listening_tags import tag_metadata


def lifetime(name: str, plays: int = 1) -> EntityLifetime:
    """Create exact selected artist counts for a small analytical fixture."""
    return EntityLifetime(listening_identity((name,)), name, name, plays, 0, 1)


def observations(
    name: str, count: int, when: str = "2024-01-10T12:00:00"
) -> tuple[ArtistPlay, ...]:
    """Create repeated recorded observations, preserving duplicates."""
    item = ArtistPlay(timestamp(when), listening_identity((name,)), name, "track")
    return (item,) * count


def test_equal_allocation_and_unknowns_reconcile_without_double_counting() -> None:
    """Three tags split an artist's plays while unknown plays remain complete."""
    catalog = TagCatalog(
        "t1-test", (tag_metadata(), tag_metadata("Beta", ("Pop", "Jazz")))
    )
    plays = (
        observations("Alpha", 3) + observations("Beta", 2) + observations("Unknown", 4)
    )
    artists = (lifetime("Alpha", 3), lifetime("Beta", 2), lifetime("Unknown", 4))
    query = ListeningQuery(date(2024, 1, 1), date(2024, 2, 29), "UTC")
    analysis = analyze_tags(plays, artists, catalog, query, 3)
    counts = {series.name: series.counts for series in analysis.series}
    assert counts["Rock"] == (1.0, 0.0)
    assert counts["Pop"] == (2.0, 0.0)
    assert counts["Jazz"] == (1.0, 0.0)
    assert counts["Unknown / no tags"] == (4.0, 0.0)
    assert sum(series.counts[0] for series in analysis.series) == 9
    assert analysis.coverage.plays == 9 and analysis.coverage.tagged_plays == 5
    assert analysis.coverage.looked_up_artists == 2
    primary = analyze_tags(plays, artists, catalog, query, 1)
    leading = {series.name: series.counts for series in primary.series}
    assert leading["Rock"][0] == 3 and leading["Pop"][0] == 2


def test_empty_unresolved_and_missing_are_distinct_but_all_remain_unknown() -> None:
    """Completed empty and unresolved lookups never fabricate genre evidence."""
    catalog = TagCatalog(
        "t1-test",
        (
            tag_metadata("Empty", (), "empty"),
            tag_metadata("Mismatch", (), "unresolved"),
        ),
    )
    plays = (
        observations("Empty", 1)
        + observations("Mismatch", 1)
        + observations("Missing", 1)
    )
    rows = tuple(lifetime(name) for name in ("Empty", "Mismatch", "Missing"))
    query = ListeningQuery(date(2024, 1, 1), date(2024, 1, 31), "UTC")
    analysis = analyze_tags(plays, rows, catalog, query, 3)
    assert analysis.series[-1].counts == (3.0,)
    assert analysis.coverage.empty_artists == 1
    assert analysis.coverage.unresolved_artists == 1
    result = present_tags(
        analysis, catalog, TagOptions(tag="unknown", search="MIS", limit=1)
    )
    assert result.total == 2 and len(result.items) == 1
    assert result.retrieved_from and result.retrieved_through
    assert (
        present_tags(analysis, catalog, TagOptions(tag="unknown", page=3)).items == ()
    )


def test_top_eight_other_and_tag_drilldown_preserve_the_complete_series() -> None:
    """Residual labels stay counted and their supporting artists stay inspectable."""
    sources = []
    plays: list[ArtistPlay] = []
    rows = []
    for index in range(10):
        name = str(index)
        sources.append(tag_metadata(name, (f"Tag {index}",)))
        plays.extend(observations(name, index + 1))
        rows.append(lifetime(name, index + 1))
    catalog = TagCatalog("t1-test", tuple(sources))
    query = ListeningQuery(date(2024, 1, 1), date(2024, 1, 31), "UTC")
    analysis = analyze_tags(tuple(plays), tuple(rows), catalog, query, 1)
    assert len(analysis.series) == 10
    assert analysis.series[-2].counts == (3.0,)
    other = present_tags(analysis, catalog, TagOptions(per_artist=1, tag="other"))
    assert other.total == 2
    key = analysis.series[0].key
    matched = present_tags(analysis, catalog, TagOptions(per_artist=1, tag=key))
    assert matched.total == 1 and matched.series == analysis.series


def test_local_month_boundaries_and_empty_history_are_explicit() -> None:
    """Timezone conversion controls buckets and an empty query stays empty."""
    catalog = TagCatalog("t1-test", (tag_metadata(),))
    plays = observations("Alpha", 1, "2024-01-31T23:30:00")
    query = ListeningQuery(date(2024, 1, 1), date(2024, 2, 29), "Europe/Berlin")
    analysis = analyze_tags(plays, (lifetime("Alpha"),), catalog, query, 1)
    assert analysis.series[0].counts == (0.0, 1.0)
    empty = analyze_tags((), (), catalog, query, 3)
    result = present_tags(empty, catalog, TagOptions())
    assert result.total == result.coverage.plays == 0
    assert result.retrieved_from is None and result.retrieved_through is None


def test_lookup_selection_is_bounded_deterministic_and_uses_retrieval_freshness() -> (
    None
):
    """Recently completed empty lookups also avoid unnecessary provider reads."""
    now = datetime(2026, 11, 21, 12, tzinfo=UTC)
    catalog = TagCatalog(
        "t1-test", (tag_metadata(), tag_metadata("Empty", (), "empty"))
    )
    rows = (
        lifetime("Alpha", 100),
        lifetime("Beta", 10),
        lifetime("Empty", 50),
        lifetime("Gamma", 10),
    )
    result = tag_fetch_candidates(rows, catalog, now, 1, False)
    assert [item.name for item in result] == ["Beta"]
    assert tag_fetch_candidates(rows, catalog, now, 1, True)[0].name == "Alpha"
    stale = replace(catalog.entries[0], fetched_at="2026-10-21T12:00:00+00:00")
    assert (
        tag_fetch_candidates(rows, TagCatalog("old", (stale,)), now, 1, False)[0].name
        == "Alpha"
    )
    assert tag_fetch_candidates((), catalog, now, 25, False) == ()
