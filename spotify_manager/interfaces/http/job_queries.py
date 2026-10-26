"""Present active jobs in registry order while the caller owns its lock."""

from collections.abc import Iterable

from spotify_manager.application.job_lifecycle import is_active_job
from spotify_manager.interfaces.http.job_records import AnalysisJob
from spotify_manager.interfaces.http.job_records import PlaylistJob
from spotify_manager.interfaces.http.models.analysis import AnalysisJobResult
from spotify_manager.interfaces.http.models.jobs import BlastJobResult


def active_playlist_snapshots(
    jobs: Iterable[PlaylistJob],
    command: str,
) -> list[BlastJobResult]:
    """Return detached active playlist/history views for one exact command.

    Args:
        jobs: Registry encounter order, observed under the caller's lock.
        command: Original command filter, without normalization.

    Returns:
        Detached views for queued, running, waiting or cancelling jobs.
    """
    results = []
    for job in jobs:
        if not is_active_job(job.result, command):
            continue
        results.append(job.result.model_copy(deep=True))
    return results


def active_analysis_snapshots(
    jobs: Iterable[AnalysisJob],
) -> list[AnalysisJobResult]:
    """Return detached active analysis views across the original registry.

    Args:
        jobs: Registry encounter order, observed under the caller's lock.

    Returns:
        Every active analysis, including different concurrently accepted commands.
    """
    results = []
    for job in jobs:
        if not is_active_job(job.result):
            continue
        results.append(job.result.model_copy(deep=True))
    return results
