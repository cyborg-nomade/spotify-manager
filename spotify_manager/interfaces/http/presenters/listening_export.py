"""Present the immutable addition list and current Spotify job progress."""

from dataclasses import dataclass

from spotify_manager.application.listening_export import PlaylistExportJob
from spotify_manager.domain.listening_export import ExportStage
from spotify_manager.domain.listening_export import ExportTrack


_PAGE_SIZE = 25


@dataclass(frozen=True)
class ExportStatus:
    """Expose the operation's phase, destination and confirmed progress."""

    identity: str
    stage: ExportStage
    message: str
    added: int
    observed: int
    total: int
    playlist_id: str | None
    name: str
    public: bool
    append: bool


@dataclass(frozen=True)
class ExportPage:
    """Carry one ordered review page and a consistent view of job progress."""

    status: ExportStatus
    page: int
    page_size: int
    items: tuple[ExportTrack, ...]


def export_status(job: PlaylistExportJob) -> ExportStatus:
    """Present verified effects and distinguish new private and existing destinations.

    Args:
        job: Process-local export using the immutable confirmed additions.

    Returns:
        User-visible progress and Spotify destination after creation or selection.
    """
    target = job.plan.target
    playlist = job.playlist or target.existing
    return ExportStatus(
        job.job_id,
        job.stage,
        job.message,
        job.added,
        job.observed,
        len(job.plan.tracks),
        playlist.identity if playlist else None,
        target.name,
        playlist.public if playlist else False,
        target.existing is not None,
    )


def export_page(job: PlaylistExportJob, page: int) -> ExportPage:
    """Page the exact ordered additions without changing job state.

    Args:
        job: Prepared or previously confirmed export.
        page: One-based page of Spotify track additions.

    Returns:
        Current status and the requested slice of the unchanged plan.
    """
    start = (page - 1) * _PAGE_SIZE
    return ExportPage(
        export_status(job),
        page,
        _PAGE_SIZE,
        job.plan.tracks[start : start + _PAGE_SIZE],
    )
