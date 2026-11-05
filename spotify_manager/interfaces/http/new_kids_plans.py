"""Validate complete New Kids plan submissions under the owning registry lock."""

from fastapi import HTTPException

from spotify_manager.application.ports.new_kids_plans import ReleasePlanSubmission
from spotify_manager.domain.new_kids_plans import validate_plan_ids
from spotify_manager.interfaces.http.job_records import PlaylistJob
from spotify_manager.interfaces.http.models.discovery import NewKidsChoiceRequest
from spotify_manager.interfaces.http.models.discovery import NewKidsPendingChoice


def accept_release_plan(
    job: PlaylistJob, pending: NewKidsPendingChoice, request: NewKidsChoiceRequest
) -> None:
    """Accept an exact current draft without allowing stale or partial decisions.

    Args:
        job: Locked job waiting for a plan.
        pending: Current published plan draft.
        request: Complete ordered selection or control request.

    Raises:
        HTTPException: Draft identity, choice or ordered selection is invalid.
    """
    if not pending.request_id or request.request_id != pending.request_id:
        raise HTTPException(409, "This release plan is no longer current.")
    answer = _submission(pending, request)
    job.submitted_plan = answer
    job.result.new_kids_pending_choice = None
    job.result.status = "running"
    job.result.detail = "Release plan submitted"
    job.choice_event.set()


def _submission(
    pending: NewKidsPendingChoice, request: NewKidsChoiceRequest
) -> ReleasePlanSubmission:
    if request.choice == "__quit__":
        return ReleasePlanSubmission("quit")
    if request.choice == "__skip__":
        return ReleasePlanSubmission("skip")
    if request.choice != "plan_select":
        raise HTTPException(400, "Choose a release plan or skip this transfer.")
    identifiers = tuple(request.release_ids)
    available = tuple(release.spotify_id for release in pending.releases)
    try:
        validate_plan_ids(identifiers, available, request.confirm_short)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    _validate_current(pending, request)
    return ReleasePlanSubmission(
        "select",
        identifiers,
        request.confirm_short,
        request.current_release_id,
        request.confirm_current,
    )


def _validate_current(
    pending: NewKidsPendingChoice, request: NewKidsChoiceRequest
) -> None:
    if not pending.migration:
        return
    current = pending.current_release_id or request.current_release_id
    if pending.current_release_id and request.current_release_id not in {None, current}:
        raise HTTPException(400, "Keep the identified current album in the plan.")
    if not current or current not in request.release_ids:
        raise HTTPException(400, "The plan must include the current album.")
    if pending.current_release_id is None and not request.confirm_current:
        raise HTTPException(400, "Confirm which edition contains the current track.")
