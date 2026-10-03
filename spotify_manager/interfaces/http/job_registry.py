"""Original process-local lookup boundaries shared by HTTP job families."""

from collections.abc import Callable
from collections.abc import Iterable
from threading import Lock

from fastapi import HTTPException

from spotify_manager.application.job_lifecycle import JobIdentity
from spotify_manager.application.job_lifecycle import first_active_job
from spotify_manager.interfaces.http.job_records import AnalysisJob
from spotify_manager.interfaces.http.job_records import PlaylistJob


def require_slot(
    jobs: Iterable[JobIdentity],
    message: str,
    command: str | None = None,
    *,
    include_command: bool = False,
) -> None:
    """Reject the first active reservation while the caller holds its lock.

    Args:
        jobs: Lazy observations from the original registry, in encounter order.
        message: Original feature-specific conflict message.
        command: Exact analysis command filter, or the whole shared playlist scope.
        include_command: Whether the original conflict detail includes its command.

    Raises:
        HTTPException: An active reservation retains the original 409 response.
    """
    existing = first_active_job(jobs, command)
    if existing is None:
        return
    detail = {"message": message, "job_id": existing.job_id}
    if include_command:
        detail["command"] = existing.command
    raise HTTPException(status_code=409, detail=detail)


def register_job[T, R](
    jobs: dict[str, T], job_id: str, job: T, snapshot: Callable[[T], R]
) -> R:
    """Register before snapshotting under the caller's existing reservation lock.

    Args:
        jobs: Original process-local registry, including retained terminal jobs.
        job_id: Opaque identifier allocated after the slot was checked.
        job: Fully constructed handle with its original initial log and signals.
        snapshot: Original overridable presentation boundary.

    Returns:
        Detached queued view captured before worker dispatch.

    Raises:
        RuntimeError: A failing snapshot boundary leaves the handle registered.
    """
    jobs[job_id] = job
    return snapshot(job)


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
