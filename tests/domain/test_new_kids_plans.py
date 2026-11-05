"""Exact ordered plan selection, bounds and default release categories."""

from dataclasses import replace

import pytest

from spotify_manager.domain.new_kids_plans import default_plan_release
from spotify_manager.domain.new_kids_plans import plan_marker
from spotify_manager.domain.new_kids_plans import select_plan
from tests.support.discovery_values import release
from tests.support.discovery_values import track


def test_explicit_order_starts_at_first_choice_without_adding_queue_album() -> None:
    """A full explicit order pins exact IDs without chronology/ranking substitution."""
    catalog = tuple(release(identity) for identity in ("queue", "a", "b", "c", "d"))
    plan = select_plan(catalog, ("d", "b", "a", "c"), False)
    assert [item.spotify_id for item in plan.releases] == ["d", "b", "a", "c"]
    assert plan.position == 0
    marker = plan_marker(plan.releases[0], track("first"))
    assert marker.spotify_id == "first" and marker.release.spotify_id == "d"


@pytest.mark.parametrize(
    "ids,short",
    [
        ((), True),
        (("a",) * 5, True),
        (("a", "a"), True),
        (("missing",), True),
        (("a",), False),
    ],
)
def test_invalid_plans_require_a_clear_operator_correction(
    ids: tuple[str, ...], short: bool
) -> None:
    """Reject size, uniqueness, unknown IDs and unconfirmed shorter plans.

    Args:
        ids: Invalid ordered selection.
        short: Submitted shorter-plan confirmation.
    """
    with pytest.raises(ValueError):
        select_plan((release("a"),), ids, short)


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_confirmed_shorter_and_full_plans_are_accepted(count: int) -> None:
    """Each supported plan length can be selected explicitly.

    Args:
        count: Selected release count.
    """
    ids = tuple(str(index) for index in range(count))
    plan = select_plan(tuple(release(identity) for identity in ids), ids, True)
    assert len(plan.releases) == count


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("Album", True),
        ("EP", True),
        ("Single", False),
        ("Compilation", False),
        ("Live", False),
    ],
)
def test_initial_view_contains_studio_albums_and_eps(kind: str, expected: bool) -> None:
    """Optional categories remain selectable without entering the initial view.

    Args:
        kind: Classified release category.
        expected: Whether initially visible.
    """
    assert default_plan_release(replace(release("a"), release_type=kind)) is expected
