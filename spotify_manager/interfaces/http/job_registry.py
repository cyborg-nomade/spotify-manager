"""Original process-local lookup boundaries shared by HTTP job families."""

from threading import Lock

from fastapi import HTTPException

from spotify_manager.interfaces.http.job_records import AnalysisJob
from spotify_manager.interfaces.http.job_records import PlaylistJob


def lookup_job[T: AnalysisJob | PlaylistJob](
    jobs: dict[str, T],
    lock: Lock,
    job_id: str,
    missing_detail: str,
    command: str | None = None,
) -> T:
    """Look up a handle under the original lock, then check its command guard.

    Args:
        jobs: Original process-local registry, including retained terminal handles.
        lock: Existing registry lock.
        job_id: Original opaque identifier.
        missing_detail: Existing feature-specific HTTP 404 text.
        command: Optional exact command identity, checked only after lookup.

    Returns:
        Existing mutable handle without a second job authority.

    Raises:
        HTTPException: The handle is missing or belongs to a different command.
    """
    with lock:
        job = jobs.get(job_id)
    if job is None or (command is not None and job.result.command != command):
        raise HTTPException(status_code=404, detail=missing_detail)
    return job
