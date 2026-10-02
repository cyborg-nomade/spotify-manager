"""Verify original mirror identity, source priority, sorting and retry decisions."""

from dataclasses import dataclass

import pytest

from spotify_manager.domain import library_analysis as rules


@dataclass(frozen=True)
class LibraryItem:
    """Supply original identity/name facts without importing file models.

    Args:
        spotify_id: Original identity, including the empty-id boundary.
        name: Original newest display name.
    """

    spotify_id: str
    name: str


def _item(identity: str, name: str = "Name") -> LibraryItem:
    return LibraryItem(identity, name)


def test_newest_identity_value_keeps_first_encounter_position() -> None:
    """Ignore empty ids and retain newest values without changing identity order."""
    first, other, newest = _item("a", "Old"), _item("b"), _item("a", "New")
    assert rules.deduplicate_models([first, _item(""), other, newest]) == [
        newest,
        other,
    ]
    assert rules.deduplicate_models([]) == []


def test_differences_retain_last_duplicate_values_and_original_encounter_order() -> (
    None
):
    """Compare identity membership while retaining the original newest diff values."""
    added, removed = rules.model_diff(
        [_item("x"), _item("y"), _item("x", "Last")],
        [_item("z"), _item("z", "Newest"), _item("w")],
    )
    assert added == [_item("z", "Newest"), _item("w")]
    assert removed == [_item("x", "Last"), _item("y")]
    assert rules.model_diff([_item("a", "Before")], [_item("a", "After")]) == (
        [],
        [],
    )


def test_statistics_count_raw_sizes_but_compare_unique_identity_membership() -> None:
    """Retain original duplicate counts, zero baselines and minimum artist divisor."""
    report = rules.stats_report_for_analysis(
        [_item("old")],
        [_item("a"), _item("a")],
        [],
        [_item("t")],
        [_item("gone")],
        [],
    )
    assert report.albums.total == 2
    assert report.albums.added == 1
    assert report.albums.removed == 1
    assert report.albums.growth == 100.0
    assert report.tracks.growth == 100.0
    assert report.artists.growth == -100.0
    assert report.avg_albums_per_artists == 2
    assert report.avg_liked_tracks_per_artists == 1
    summary = rules.resource_summary(
        "albums", "source", [_item("old")], [_item("a")], 3
    )
    assert (
        summary.previous,
        summary.current,
        summary.added,
        summary.removed,
        summary.skipped,
    ) == (1, 1, 1, 1, 3)


@pytest.mark.parametrize(
    ("full", "candidate_names", "retained_names"),
    [
        (True, ["Live", "Export only", "Live only"], []),
        (False, ["Export only"], ["Live", "Live only"]),
    ],
)
def test_verification_priority_and_incremental_retention(
    full: bool,
    candidate_names: list[str],
    retained_names: list[str],
) -> None:
    """Give partial live facts precedence and retain stored rows during incrementals.

    Args:
        full: Original complete-versus-incremental verification choice.
        candidate_names: Expected original candidate names in encounter order.
        retained_names: Expected original immediately retained names.
    """
    candidates, retained = rules.verification_candidates(
        [_item("a", "Stored")],
        [_item("a", "Export"), _item("b", "Export only")],
        [_item("a", "Live"), _item("c", "Live only")],
        full,
    )
    assert [item.name for item in candidates] == candidate_names
    assert [item.name for item in retained] == retained_names


@pytest.mark.parametrize(
    ("base", "maximum", "attempt", "expected"),
    [
        (0, 10, 1, 0),
        (-1, 10, 1, 0),
        (10, 0, 1, 0),
        (10, -1, 1, 0),
        (10, 100, -3, 10),
        (10, 100, 1, 10),
        (10, 100, 3, 40),
        (10, 100, 40, 100),
        (30, 10, 1, 10),
    ],
)
def test_retry_delay_matches_original_capped_exponential(
    base: int,
    maximum: int,
    attempt: int,
    expected: int,
) -> None:
    """Retain original zero waits and bounded exponent behavior.

    Args:
        base: Original initial delay.
        maximum: Original cap.
        attempt: Original one-based attempt, including permissive negative inputs.
        expected: Original capped delay.
    """
    assert rules.retry_delay(base, maximum, attempt) == expected
