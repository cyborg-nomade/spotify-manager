"""Planning chronology changes display order without changing explicit plans."""

from dataclasses import replace

import pytest

from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.new_kids_plans import ReleasePlan
from spotify_manager.domain.new_kids_plans import planning_catalogue
from spotify_manager.domain.new_kids_plans import select_plan
from tests.support.discovery_values import release


def _release(identity: str, title: str, date: str) -> RankedRelease:
    return replace(release(identity), name=title, release_date=date)


def test_dates_precede_titles_popularity_and_release_categories() -> None:
    """Chronology applies equally to studios and every optional release category."""
    records = (
        _release("new", "Alpha", "2024"),
        replace(_release("live", "Zulu", "1990"), release_type="Live", tier=3),
        replace(_release("ep", "Beta", "2000"), release_type="EP"),
        replace(_release("single", "Charlie", "2001"), release_type="Single"),
        replace(_release("comp", "Delta", "2002"), release_type="Compilation"),
    )
    ordered = planning_catalogue(records)
    assert [item.spotify_id for item in ordered] == [
        "live",
        "ep",
        "single",
        "comp",
        "new",
    ]
    assert ordered[0] is records[1] and records[0].spotify_id == "new"


@pytest.mark.parametrize("partial", ["2000", "2000-01", "2000-01-01"])
def test_partial_dates_use_first_day_and_equal_dates_use_title(partial: str) -> None:
    """Date precision is retained while equivalent days compare alphabetically.

    Args:
        partial: Date with year, month or full-day precision.
    """
    records = (
        _release("z", "Zulu", partial),
        _release("a", "alpha", "2000-01-01"),
        _release("later", "Aardvark", "2000-02"),
    )
    assert [item.spotify_id for item in planning_catalogue(records)] == [
        "a",
        "z",
        "later",
    ]
    assert records[0].release_date == partial


@pytest.mark.parametrize("unknown", ["Unknown", "", "not-a-date", "2000-02-30"])
def test_unknown_and_calendar_invalid_dates_sort_after_known_dates(
    unknown: str,
) -> None:
    """Missing dates cannot appear ahead of a valid late release.

    Args:
        unknown: Missing or invalid calendar value.
    """
    records = (_release("unknown", "Alpha", unknown), _release("known", "Zulu", "9999"))
    assert planning_catalogue(records) == (records[1], records[0])


def test_equal_dates_and_casefolded_titles_have_a_stable_exact_id_tiebreak() -> None:
    """Repeated observations cannot shuffle indistinguishable named editions."""
    records = (_release("z", "TITLE", "2000"), _release("a", "title", "2000"))
    assert planning_catalogue(records) == planning_catalogue(tuple(reversed(records)))
    assert planning_catalogue(records)[0].spotify_id == "a"
    assert planning_catalogue(()) == ()


def test_catalogue_order_never_reorders_an_existing_or_new_selected_plan() -> None:
    """The catalogue only changes available options, never the listening cursor."""
    records = (_release("new", "Newest", "2024"), _release("old", "Oldest", "1990"))
    existing = ReleasePlan(records, 1)
    selected = select_plan(planning_catalogue(records), ("new", "old"), True)
    assert selected.releases == existing.releases and existing.position == 1
