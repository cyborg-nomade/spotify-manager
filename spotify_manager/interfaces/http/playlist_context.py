"""Process-local resources shared by the threaded playlist workers."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from spotify_manager.application.job_lifecycle import append_log
from spotify_manager.application.job_lifecycle import retain_logs
from spotify_manager.interfaces.http.job_records import PlaylistJob
from spotify_manager.interfaces.http.job_registry import lookup_job
from spotify_manager.interfaces.http.models.analysis import AnalysisJobLog


@dataclass(frozen=True)
class PlaylistContext:
    """Own a worker's registry, synchronization and diagnostic resources.

    Args:
        registry: Existing process-local job authority.
        lock: Lock protecting registry entries and response snapshots.
        logger: Server diagnostic logger.
        clock: Original overridable clock used for timestamps.
        log_entry: Original log timestamp and serialization boundary.
        log_limit: Maximum retained entries per job.
    """

    registry: dict[str, PlaylistJob]
    lock: Lock
    logger: logging.Logger
    clock: type[datetime]
    log_entry: Callable[[int, str], AnalysisJobLog]
    log_limit: int

    def lookup(self, job_id: str, command: str | None = None) -> PlaylistJob:
        """Resolve a worker handle under the registry lock.

        Args:
            job_id: Existing job identity.
            command: Optional expected command.

        Returns:
            The registered mutable job handle.

        Raises:
            HTTPException: The job is missing or belongs to another command.
        """
        return lookup_job(
            self.registry, self.lock, job_id, "playlist job not found", command
        )

    def append(self, job: PlaylistJob, message: str) -> None:
        """Append an ordered event while the caller holds the registry lock.

        Args:
            job: Registered job receiving the event.
            message: Original visible message; empty messages are ignored.
        """
        if not message:
            return
        job.next_log_sequence = append_log(
            job.result.logs, job.next_log_sequence, message, self.log_entry
        )
        retain_logs(job.result.logs, self.log_limit)
