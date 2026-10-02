"""Original serial nightly refresh, reconnect, poll and safe connection checks."""

from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import tzinfo
from typing import Protocol
from typing import cast

from spotify_manager.application.automation_values import ACTIVE_STATUSES
from spotify_manager.application.automation_values import BLOCKED_RETRY_SECONDS
from spotify_manager.application.automation_values import DURABLE_ARTIFACT_FILENAMES
from spotify_manager.application.automation_values import FULL_REBUILD_JOBS
from spotify_manager.application.automation_values import JOBS
from spotify_manager.application.automation_values import POLL_SECONDS
from spotify_manager.application.automation_values import ApiError
from spotify_manager.application.automation_values import AutomationError
from spotify_manager.application.automation_values import JobLostError
from spotify_manager.application.automation_values import JobSpec
from spotify_manager.domain.automation_calendar import artifacts_are_fresh


class SpaceAccess(Protocol):
    """Supply authenticated requests, bounded waits and remaining maintenance time."""

    deadline: datetime

    def request(
        self,
        method: str,
        path: str,
        *,
        retry_transient: bool = True,
        deadline: datetime | None = None,
    ) -> object:
        """Observe the original decoded API response.

        Args:
            method: Original HTTP verb.
            path: Original path and query.
            retry_transient: Original retry permission.
            deadline: Optional original cancellation grace deadline.

        Returns:
            Original unvalidated decoded JSON.
        """
        ...

    def sleep(self, seconds: int) -> None:
        """Wait within the original maintenance boundary.

        Args:
            seconds: Original requested delay.
        """
        ...

    def remaining_seconds(self) -> float:
        """Observe remaining maintenance time.

        Returns:
            Original signed seconds remaining.
        """
        ...


def conflict_detail(error: ApiError) -> dict[str, object]:
    """Retain the original permissive nested conflict container.

    Args:
        error: Original HTTP failure.

    Returns:
        Original detail object or an empty mapping.
    """
    if not isinstance(error.payload, dict):
        return {}
    detail = error.payload.get("detail")
    return detail if isinstance(detail, dict) else {}


def start_job(client: SpaceAccess, spec: JobSpec, emit: Callable[[str], None]) -> str:
    """Start or reconnect in original order, waiting out incompatible active jobs.

    Args:
        client: Original authenticated API observations.
        spec: Original command and routes.
        emit: Original visible progress output.

    Returns:
        Original accepted or compatible existing job identity.

    Raises:
        ApiError: The original request fails outside conflict handling.
        AutomationError: Original successful response has no job identity.
    """
    while True:
        identity = _start_attempt(client, spec, emit)
        if identity:
            return identity
        client.sleep(BLOCKED_RETRY_SECONDS)


def _start_attempt(
    client: SpaceAccess, spec: JobSpec, emit: Callable[[str], None]
) -> str:
    try:
        payload = client.request("POST", spec.start_path, retry_transient=True)
    except ApiError as error:
        if error.status != 409:
            raise
        return _reconnect(client, spec, error, emit)
    if not isinstance(payload, dict) or not payload.get("job_id"):
        raise AutomationError(f"{spec.label} returned no job id.")
    identity = str(payload["job_id"])
    emit(f"Started {spec.label} as {identity}.")
    return identity


def _reconnect(
    client: SpaceAccess, spec: JobSpec, error: ApiError, emit: Callable[[str], None]
) -> str:
    detail = conflict_detail(error)
    job_id = str(detail.get("job_id") or "")
    blocker = str(detail.get("command") or "")
    compatible = _compatible_job(client, spec, job_id, blocker)
    if job_id and compatible and (not blocker or blocker == spec.command):
        emit(f"Reconnected to existing {spec.label} job {job_id}.")
        return job_id
    emit(f"{spec.label} is blocked by {blocker or 'another active job'}; waiting.")
    return ""


def _compatible_job(
    client: SpaceAccess, spec: JobSpec, job_id: str, blocker: str
) -> bool:
    if not job_id or (blocker and blocker != spec.command):
        return True
    if (
        spec.command != "update_scrobble_history"
        or "full_rebuild=true" not in spec.start_path
    ):
        return True
    # External JSON intentionally retains the original unchecked .get behavior.
    running = cast(
        dict[str, object], client.request("GET", spec.status_path.format(job_id=job_id))
    )
    return bool(running.get("history_full_rebuild")) and not running.get("dry_run")


def cancel_job(
    client: SpaceAccess,
    spec: JobSpec,
    job_id: str,
    now: Callable[[], datetime],
    emit: Callable[[str], None],
) -> None:
    """Request the original cancellation with a separate three-minute grace period.

    Args:
        client: Original authenticated API observations.
        spec: Original cancel route.
        job_id: Original active identity.
        now: Original separately observed UTC clock.
        emit: Original cancellation presentation.

    Raises:
        ApiError: Original cancellation fails outside accepted 404/409 statuses.
    """
    emit(f"Cancelling {spec.label} at the maintenance deadline.")
    grace = now() + timedelta(minutes=3)
    try:
        client.request(
            "POST",
            spec.cancel_path.format(job_id=job_id),
            retry_transient=False,
            deadline=grace,
        )
    except ApiError as error:
        if error.status not in {404, 409}:
            raise


def poll_job(
    client: SpaceAccess,
    spec: JobSpec,
    job_id: str,
    cancel: Callable[[JobSpec, str], None],
    emit: Callable[[str], None],
) -> str:
    """Retain polling, changed-status output and original completion boundaries.

    Args:
        client: Original API and remaining-time observations.
        spec: Original status route and display label.
        job_id: Original active job identity.
        cancel: Original delayed cancellation stage.
        emit: Original status presentation.

    Returns:
        Original completed, paused or deadline outcome.

    Raises:
        JobLostError: The original handle disappears after restart.
        AutomationError: Original status shape, failure or value is invalid.
    """
    previous: tuple[str, str] | None = None
    while True:
        if client.remaining_seconds() <= 0:
            cancel(spec, job_id)
            return "deadline"
        current = _read_status(client, spec, job_id)
        if current != previous:
            emit(f"{spec.label}: {current[0]} - {current[1]}")
            previous = current
        outcome = _status_outcome(spec, *current)
        if outcome is not None:
            return outcome
        client.sleep(POLL_SECONDS)


def _read_status(client: SpaceAccess, spec: JobSpec, job_id: str) -> tuple[str, str]:
    try:
        payload = client.request("GET", spec.status_path.format(job_id=job_id))
    except ApiError as error:
        if error.status == 404:
            raise JobLostError(f"Lost {spec.label} after a Space restart.") from error
        raise
    if not isinstance(payload, dict):
        raise AutomationError(f"{spec.label} returned an invalid job status.")
    return str(payload.get("status") or ""), str(payload.get("detail") or "")


def _status_outcome(spec: JobSpec, status: str, detail: str) -> str | None:
    if status in {"completed", "paused"}:
        return status
    if status == "cancelled":
        return "paused"
    if status == "failed":
        raise AutomationError(f"{spec.label} ended as {status}: {detail}")
    if status not in ACTIVE_STATUSES:
        raise AutomationError(f"{spec.label} returned unknown status {status!r}.")
    return None


def run_job(
    client: SpaceAccess,
    spec: JobSpec,
    start: Callable[[JobSpec], str],
    poll: Callable[[JobSpec, str], str],
    emit: Callable[[str], None],
) -> str:
    """Resume the original durable workflow after a lost in-memory handle.

    Args:
        client: Original caller-owned API lifetime.
        spec: Original job specification.
        start: Original start/reconnect stage.
        poll: Original polling stage.
        emit: Original restart presentation.

    Returns:
        Original terminal outcome.
    """
    while True:
        job_id = start(spec)
        try:
            return poll(spec, job_id)
        except JobLostError:
            emit(f"{spec.label} handle was lost; resuming from its checkpoint.")


def nightly_refresh(
    client: SpaceAccess,
    jobs: tuple[JobSpec, ...],
    threshold: datetime | None,
    timezone: tzinfo,
    fresh: Callable[[datetime], bool],
    run: Callable[[JobSpec], str],
    emit: Callable[[str], None],
) -> int:
    """Run original serial refreshes after health and optional duplicate detection.

    Args:
        client: Original authenticated API observations.
        jobs: Original ordered job manifest.
        threshold: Original optional window freshness boundary.
        timezone: Original local presentation timezone.
        fresh: Original delayed durable-artifact observation.
        run: Original start/poll/resume stage.
        emit: Original progress presentation.

    Returns:
        Original successful exit for completion, safe pause or deadline.
    """
    emit(
        "Nightly refresh deadline: "
        + f"{client.deadline.astimezone(timezone).isoformat()} (Europe/Berlin)"
    )
    client.request("GET", "/health")
    emit("Space is awake and healthy.")
    if threshold is not None and fresh(threshold):
        emit(
            "All four durable artifacts were already refreshed during this "
            "maintenance window; skipping the duplicate trigger."
        )
        return 0
    mode = "full rebuild" if jobs == FULL_REBUILD_JOBS else "incremental"
    emit(f"Refresh mode: {mode}.")
    return _run_jobs(jobs, run, emit)


def _run_jobs(
    jobs: tuple[JobSpec, ...],
    run: Callable[[JobSpec], str],
    emit: Callable[[str], None],
) -> int:
    for index, spec in enumerate(jobs):
        outcome = run(spec)
        if outcome == "paused":
            emit(f"{spec.label} paused cleanly; remaining jobs will resume tomorrow.")
            return 0
        if outcome == "deadline":
            emit("Maintenance window closed; progress was saved.")
            return 0
        emit(f"Completed {spec.label} ({index + 1}/{len(jobs)}).")
    emit("All nightly library refreshes completed.")
    return 0


def durable_artifacts_are_fresh(
    client: SpaceAccess,
    threshold: datetime,
    decode: Callable[[object], dict[str, datetime] | None],
) -> bool:
    """Apply original freshness rules to explicitly decoded artifact observations.

    Args:
        client: Original status request.
        threshold: Original inclusive window boundary.
        decode: Original tolerant timestamp and container parser.

    Returns:
        Original all-artifacts freshness decision.
    """
    updated = decode(client.request("GET", "/library-mirrors/status"))
    return updated is not None and artifacts_are_fresh(
        updated, DURABLE_ARTIFACT_FILENAMES, threshold
    )


def connection_check(client: SpaceAccess, emit: Callable[[str], None]) -> int:
    """Check original auth, durable state and active jobs without starting routines.

    Args:
        client: Original authenticated API observations.
        emit: Original successful check presentation.

    Returns:
        Original successful exit.

    Raises:
        AutomationError: An original prerequisite or active-job check fails.
    """
    client.request("GET", "/health")
    auth = client.request("GET", "/auth/check")
    if not isinstance(auth, dict) or auth.get("status") != "ok":
        raise AutomationError("The Space automation token was not accepted.")
    _check_artifacts(client.request("GET", "/library-mirrors/status"))
    state = client.request("GET", "/state/summary")
    if not isinstance(state, dict) or not state.get("revision"):
        raise AutomationError("The shared state dataset is unavailable.")
    paths = _job_paths(client.request("GET", "/openapi.json"))
    _check_active_jobs(client, paths)
    emit("Automation authentication, shared state, and all four artifacts are healthy.")
    emit(f"No active jobs across {len(paths)} routine endpoints.")
    return 0


def _check_artifacts(payload: object) -> None:
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list) or len(files) != len(JOBS):
        raise AutomationError("The durable library-data status is incomplete.")
    missing = []
    for item in files:
        if not isinstance(item, dict) or not item.get("exists"):
            # Preserve original native .get failure on non-object rows.
            missing.append(str(item.get("filename") or "unknown"))
    if missing:
        raise AutomationError("Durable artifacts are missing: " + ", ".join(missing))


def _job_paths(schema: object) -> list[str]:
    paths = schema.get("paths") if isinstance(schema, dict) else None
    if not isinstance(paths, dict):
        raise AutomationError("Could not inspect active-job endpoints.")
    selected = []
    for path in paths:
        if path.endswith("-jobs") and "{" not in path:
            selected.append(path)
    if not selected:
        raise AutomationError("No active-job endpoints were found.")
    return sorted(selected)


def _check_active_jobs(client: SpaceAccess, paths: list[str]) -> None:
    for path in paths:
        jobs = client.request("GET", path)
        if not isinstance(jobs, list):
            raise AutomationError(f"Invalid active-job response from {path}.")
        if jobs:
            raise AutomationError(f"Active jobs at {path}; wait before deploying.")
