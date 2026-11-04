"""Validate manual Spotify matching submissions under the registry lock."""

from fastapi import HTTPException

from spotify_manager.interfaces.http import jobs
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.track_matching import (
    TrackMatchChoiceRequest,
)


def submit_track_match(
    job_id: str, command: str, request: TrackMatchChoiceRequest
) -> BlastJobResult:
    """Accept a choice only for the current request of the requested routine.

    Args:
        job_id: Reconnectable job identity.
        command: Owning routine identity.
        request: Candidate ID or explicit no-match submission.

    Returns:
        Detached updated job view.

    Raises:
        HTTPException: The request is stale, cancelled, unknown or invalid.
    """
    job = jobs.get_blast_job(job_id, command=command)
    with jobs._blast_jobs_lock:
        pending = job.result.track_match_pending_choice
        if job.result.status != "waiting" or pending is None:
            raise HTTPException(409, "The job is not waiting for a track match")
        if pending.request_id != request.request_id:
            raise HTTPException(409, "This track matching request is no longer current")
        options = pending.albums if pending.kind == "album" else pending.candidates
        identifiers = {candidate.spotify_id for candidate in options}
        if request.choice and request.choice not in identifiers:
            raise HTTPException(
                400, f"Choose an offered Spotify {pending.kind} or No match"
            )
        job.submitted_choice = request.choice
        job.result.track_match_pending_choice = None
        job.result.status = "running"
        job.result.detail = "Spotify match choice submitted"
        job.choice_event.set()
        return jobs._blast_job_snapshot(job)
