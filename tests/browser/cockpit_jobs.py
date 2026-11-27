"""Model a small set of synthetic jobs for the actual cockpit UI."""

from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from fastapi import APIRouter
from fastapi import HTTPException
from fastapi import Request

from spotify_manager.interfaces.http.models.analysis import AnalysisJobLog
from spotify_manager.interfaces.http.models.analysis import AnalysisJobResult
from spotify_manager.interfaces.http.models.analysis import AnalysisResourceProgress
from spotify_manager.interfaces.http.models.jobs import BlastJobResult
from spotify_manager.interfaces.http.models.requeue import RequeueChoiceRequest
from spotify_manager.interfaces.http.models.requeue import RequeuePendingChoice


router = APIRouter(prefix="/commands")
MirrorResource = Literal["albums", "tracks", "artists"]
ACTIVE = {"running", "waiting"}
BLAST = "blast-from-the-past"
REQUEUE = "flush-requeue-for-a-dream"
HISTORY = "update-scrobble-history"
EMPTY_LISTS = frozenset(
    {
        "blast-from-the-past-artists",
        "check-new-releases",
        "daily-mind-radio",
        "fill-palace-of-memory",
        "fill-queue-from-lastfm",
        "fill-sauvignon-from-lastfm",
        "flush-new-kids",
        "flush-new-wine",
        "flush-queue",
        "flush-queue-2",
        "flush-queue-3",
        "flush-slow-listening",
        "found-art",
        "new-year",
        "plan-discographies",
        "something-old",
    }
)


@dataclass
class JobFixture:
    """Keep simulated jobs available to reload and cancel within one process."""

    mirrors: dict[str, AnalysisJobResult] = field(default_factory=dict)
    playlists: dict[str, list[BlastJobResult]] = field(default_factory=dict)


_jobs = JobFixture()


def reset_jobs() -> None:
    """Clear the sample job registry between tests."""
    global _jobs
    _jobs = JobFixture()


def _job_conflict(job_id: str, command: str) -> HTTPException:
    return HTTPException(409, {"job_id": job_id, "command": command})


@router.get("/check-new-releases-state")
async def release_snapshot() -> dict[str, str]:
    """Return an empty synthetic release cursor with a stable fingerprint."""
    return {"fingerprint": "sample-release-check"}


@router.post("/refresh-library-mirrors/{resource}")
async def start_mirror(
    resource: MirrorResource, full_rebuild: bool = False
) -> AnalysisJobResult:
    """Start a sample mirror job with visible progress.

    Args:
        resource: Which cockpit source was selected.
        full_rebuild: Whether the operator selected Full.

    Returns:
        Pollable sample mirror job.

    Raises:
        HTTPException: The sample source already has a running job.
    """
    for previous in _jobs.mirrors.values():
        if previous.mirror_resource == resource and previous.status in ACTIVE:
            raise _job_conflict(previous.job_id, previous.command)
    job_id = f"sample-mirror-{resource}-{len(_jobs.mirrors) + 1}"
    job = AnalysisJobResult(
        job_id=job_id,
        command="library_analysis",
        detail="Comparing sample Spotify library",
        status="running",
        mirror_resource=resource,
        full_rebuild=full_rebuild,
        resources={
            resource: AnalysisResourceProgress(
                completed=84, total=120, status="Running"
            )
        },
        logs=[
            AnalysisJobLog(
                sequence=1,
                timestamp="2024-10-31T08:23:00Z",
                message="Checked 84 of 120 sample records",
            )
        ],
    )
    _jobs.mirrors[job_id] = job
    return job


@router.get("/library-analysis-jobs")
async def active_mirrors() -> list[AnalysisJobResult]:
    """Return active mirror jobs for the reload path."""
    return [job for job in _jobs.mirrors.values() if job.status in ACTIVE]


@router.get("/library-analysis-jobs/{job_id}")
async def mirror_job(job_id: str) -> AnalysisJobResult:
    """Return the sample mirror job selected by the poller.

    Args:
        job_id: Identifier received at launch.

    Returns:
        Current job state.

    Raises:
        HTTPException: The sample job does not exist.
    """
    job = _jobs.mirrors.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown sample mirror job.")
    return job


@router.post("/library-analysis-jobs/{job_id}/cancel")
async def cancel_mirror(job_id: str) -> AnalysisJobResult:
    """Cancel the selected fixture mirror refresh.

    Args:
        job_id: Identifier of the active refresh.

    Returns:
        Cancelled job with its last reported progress.
    """
    job = await mirror_job(job_id)
    job.status = "cancelled"
    job.detail = "Sample library refresh cancelled"
    return job


def _store_playlist(route: str, job: BlastJobResult) -> BlastJobResult:
    history = _jobs.playlists.setdefault(route, [])
    current = history[-1] if history else None
    if current is not None and current.status in ACTIVE:
        raise _job_conflict(current.job_id, current.command)
    job.job_id = f"{job.job_id}-{len(history) + 1}"
    history.append(job)
    return job


@router.post(f"/{BLAST}")
async def start_blast(
    dry_run: bool, count: int | None = None, max_playlist_length: int | None = None
) -> BlastJobResult:
    """Simulate a Blast launch using the cockpit's Count or Cap inputs.

    Args:
        dry_run: Whether the cockpit requested a preview.
        count: Explicit requested track count.
        max_playlist_length: Alternative playlist cap.

    Returns:
        The active sample job.
    """
    target = f"cap of {max_playlist_length}" if count is None else f"{count} tracks"
    return _store_playlist(
        BLAST,
        BlastJobResult(
            job_id="sample-blast",
            dry_run=dry_run,
            status="running",
            detail=f"Reviewing sample listening history for {target}",
        ),
    )


def _successor(second: bool = False) -> RequeuePendingChoice:
    return RequeuePendingChoice(
        request_id="sample-choice-2" if second else "sample-choice-1",
        artist="Vesper Static",
        source_track="Last Light",
        source_release="Soft Relay",
        release_id="sample-release-2" if second else "sample-release-1",
        release_name="Only a Receiver" if second else "Rooms Without Windows",
        release_type="album",
        release_date="2016" if second else "2012",
        total_tracks=7 if second else 9,
    )


@router.post(f"/{REQUEUE}")
async def start_requeue(dry_run: bool) -> BlastJobResult:
    """Offer the first sample successor album for review.

    Args:
        dry_run: Whether the cockpit requested a preview.

    Returns:
        The sample job waiting for a choice.
    """
    return _store_playlist(
        REQUEUE,
        BlastJobResult(
            job_id="sample-requeue",
            command="flush_requeue_for_a_dream",
            dry_run=dry_run,
            status="waiting",
            detail="Awaiting an album choice",
            requeue_pending_choice=_successor(),
        ),
    )


@router.post(f"/{HISTORY}")
async def start_history(
    request: Request, dry_run: bool, full_rebuild: bool
) -> BlastJobResult:
    """Simulate a history refresh against a fixed offline export.

    Args:
        request: Provides the count in this process's published fixture.
        dry_run: Whether the cockpit requested a preview.
        full_rebuild: Whether the operator selected Full.

    Returns:
        Completed sample refresh.
    """
    return _store_playlist(
        HISTORY,
        BlastJobResult(
            job_id="sample-history",
            command="update_scrobble_history",
            status="completed",
            detail="Sample history refreshed",
            dry_run=dry_run,
            history_full_rebuild=full_rebuild,
            history_scrobbles=request.app.state.history_count,
            history_export_scrobbles=request.app.state.history_count,
        ),
    )


@router.get("/{route}-jobs")
async def active_playlist_jobs(route: str) -> list[BlastJobResult]:
    """Return fixture activity for a known cockpit job family.

    Args:
        route: Job-family path segment.

    Returns:
        The active sample job, if present.

    Raises:
        HTTPException: The job family is outside the fixture.
    """
    if route in EMPTY_LISTS:
        return []
    if route not in {BLAST, REQUEUE, HISTORY}:
        raise HTTPException(404, "Unknown sample job family.")
    return [job for job in _jobs.playlists.get(route, []) if job.status in ACTIVE]


@router.get("/{route}-jobs/{job_id}")
async def playlist_job(route: str, job_id: str) -> BlastJobResult:
    """Poll a previously launched fixture job.

    Args:
        route: Job-family path segment.
        job_id: Identifier received at launch.

    Returns:
        Current state of the sample job.

    Raises:
        HTTPException: No matching fixture job exists.
    """
    for job in _jobs.playlists.get(route, []):
        if job.job_id == job_id:
            return job
    raise HTTPException(404, "Unknown sample playlist job.")


@router.post(f"/{REQUEUE}-jobs/{{job_id}}/choice")
async def choose_album(job_id: str, update: RequeueChoiceRequest) -> BlastJobResult:
    """Apply a decision to the exact pending album.

    Args:
        job_id: Identifier of the sample Requeue job.
        update: The observed choice ID and decision.

    Returns:
        The next choice or a terminal state.

    Raises:
        HTTPException: The choice no longer matches the offered album.
    """
    job = await playlist_job(REQUEUE, job_id)
    choice = job.requeue_pending_choice
    if choice is None or choice.request_id != update.request_id:
        raise HTTPException(409, "That sample album choice is no longer active.")
    if update.choice == "skip" and choice.request_id == "sample-choice-1":
        job.requeue_pending_choice = _successor(second=True)
        return job
    job.requeue_pending_choice = None
    job.status = "cancelled" if update.choice == "cancel" else "completed"
    job.detail = {
        "accept": "Sample album accepted",
        "skip": "No remaining sample albums",
        "cancel": "Sample album review cancelled",
    }[update.choice]
    return job


@router.post("/{route}-jobs/{job_id}/cancel")
async def cancel_playlist(route: str, job_id: str) -> BlastJobResult:
    """Stop the matched sample job and clear any pending choice.

    Args:
        route: Job-family path segment.
        job_id: Identifier of the active job.

    Returns:
        The cancelled sample job.
    """
    job = await playlist_job(route, job_id)
    job.status = "cancelled"
    job.detail = "Sample playlist job cancelled"
    job.requeue_pending_choice = None
    return job
