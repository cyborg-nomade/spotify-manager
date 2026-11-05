"""Encode and validate additive pinned plans in the existing artist namespace."""

from dataclasses import asdict

from spotify_manager.application.new_kids_state import release_from_record
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain.new_kids_plans import ReleasePlan
from spotify_manager.domain.new_kids_plans import select_plan


def plan_record(plan: ReleasePlan) -> dict[str, object]:
    """Serialize exact chosen releases and acknowledged progression.

    Args:
        plan: Accepted ordered plan.

    Returns:
        Versioned additive artist-progress record.
    """
    return {
        "version": 1,
        "releases": [asdict(release) for release in plan.releases],
        "position": plan.position,
    }


def saved_plan(progress: dict[str, object]) -> ReleasePlan | None:
    """Read a pinned plan without treating malformed data as an unplanned artist.

    Args:
        progress: Existing artist record retaining unrelated fields.

    Returns:
        Valid pinned plan, or None only when the optional key is absent.

    Raises:
        NewKidsStateError: The saved plan cannot safely identify the next release.
    """
    if "release_plan" not in progress:
        return None
    raw = progress["release_plan"]
    if not isinstance(raw, dict) or raw.get("version") != 1:
        raise NewKidsStateError("New Kids release plan is invalid.")
    values, position = raw.get("releases"), raw.get("position")
    if not isinstance(values, list) or type(position) is not int:
        raise NewKidsStateError("New Kids release plan is invalid.")
    try:
        releases = tuple(release_from_record(value) for value in values)
        select_plan(releases, tuple(item.spotify_id for item in releases), True)
    except (KeyError, TypeError, ValueError) as exc:
        raise NewKidsStateError("New Kids release plan is invalid.") from exc
    if not 0 <= position < len(releases):
        raise NewKidsStateError("New Kids release plan position is invalid.")
    return ReleasePlan(releases, position)
