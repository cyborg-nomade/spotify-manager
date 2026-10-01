"""Protect market-edition preference and calendar-ordered retained-single reviews."""

from dataclasses import replace
from datetime import date

from spotify_manager.domain.release_catalog import current_editions
from spotify_manager.domain.release_catalog import eligible_records
from spotify_manager.domain.release_catalog import ordered_releases
from spotify_manager.domain.release_check_values import PendingSingle
from tests.support.release_run import TRACK
from tests.support.release_run import release


START = date(2026, 1, 1)
END = date(2026, 9, 25)


def test_current_editions_keep_identity_order_and_duplicate_encounter_order() -> None:
    """Prefer count then identity without shifting first-identity insertion order."""
    original = release("b", count=4)
    winner = release("a", count=6)
    later = release("c", count=6)
    other = release("other", title="Other")
    current, duplicates = current_editions((original, other, winner, later), START, END)
    assert current == (winner, other)
    assert duplicates == (original, later)


def test_current_editions_keep_first_identical_observation() -> None:
    """An identical preference key retains the first actual object."""
    first = release("same")
    second = replace(first)
    current, duplicates = current_editions((first, second), START, END)
    assert current[0] is first and duplicates[0] is second


def test_current_editions_require_valid_overlapping_dates() -> None:
    """Exclude invalid, past and definitely future records from current editions."""
    candidates = (
        release(stamp="invalid"),
        release("old", stamp="2025-12-31"),
        release("future", stamp="2027-01-01"),
        release("current"),
    )
    assert current_editions(candidates, START, END) == ((candidates[-1],), ())


def test_eligible_records_preserve_order_and_rank_scope() -> None:
    """Keep eligible albums/EPs while applying their original rank/title exclusions."""
    candidates = (
        release("single", kind="Single"),
        release("album"),
        release("excluded", title="Greatest Hits"),
        release("ep", kind="EP"),
        release("live", title="Live at Home"),
    )
    assert eligible_records(candidates, 51) == (candidates[1], candidates[3])
    assert eligible_records(candidates, 1) == (
        candidates[1],
        candidates[3],
        candidates[4],
    )


def test_review_order_adds_absent_pending_releases_and_retains_current_metadata() -> (
    None
):
    """Current identities prevail; absent singles return in date/type/title/ID order."""
    current = release("current", stamp="2026-09-01")
    absent = release("absent", kind="Single", stamp="2025-12-31")
    obsolete = replace(current, name="Obsolete")
    invalid = release("invalid", stamp="invalid")
    pending = {
        "current": PendingSingle("artist", obsolete, TRACK),
        "absent": PendingSingle("artist", absent, TRACK),
        "invalid": PendingSingle("artist", invalid, TRACK),
    }
    assert ordered_releases((current,), pending) == (absent, current, invalid)


def test_review_order_uses_type_title_and_identity_for_date_ties() -> None:
    """Calendar ties use kind, casefolded title and identity in that order."""
    candidates = (
        release("z", title="beta"),
        release("b", title="Alpha"),
        release("a", title="ALPHA"),
        release("single", kind="Single"),
    )
    assert ordered_releases(candidates, {}) == (
        candidates[2],
        candidates[1],
        candidates[0],
        candidates[3],
    )
