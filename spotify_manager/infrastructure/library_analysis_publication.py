"""Analysis undo and recovery storage using explicit named operations."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.library_analysis_publication import Resources
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import ResourceSyncSummary
from spotify_manager.infrastructure import library_analysis_backups as backups
from spotify_manager.infrastructure.analysis_file_ports import (
    BlockingAnalysisFiles as AnalysisFiles,
)
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.library_records import current_stats_history_key
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.models.stats import StatsReport


@dataclass(frozen=True)
class AnalysisBackups:
    """Own undo storage for one analysis invocation.

    Args:
        files: Analysis storage owner.
    """

    files: AnalysisFiles

    async def analysis_backup(
        self,
        paths: LibraryAnalysisPaths,
        run_id: str,
        previous: Resources,
        current: Resources,
        report: StatsReport,
        summaries: tuple[ResourceSyncSummary, ...],
    ) -> Path:
        """Copy all original outputs before recording complete analysis differences.

        Args:
            paths: Original output family.
            run_id: Original sortable run identity.
            previous: Original complete pre-analysis models.
            current: Original sorted post-analysis models.
            report: Original complete analysis counts.
            summaries: Original ordered resource outcomes.

        Returns:
            Original accepted backup directory.
        """
        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(
                    backups.create_backup_manifest,
                    paths,
                    run_id,
                    previous,
                    current,
                    report,
                    summaries,
                    self.files,
                )
            )
            return await finish_blocking(file_operation)

    async def mirror_backup(
        self,
        paths: LibraryAnalysisPaths,
        run_id: str,
        previous: Resources,
        current: Resources,
        summaries: tuple[ResourceSyncSummary, ...],
    ) -> Path:
        """Preserve original interleaved album/track copies and difference recording.

        Args:
            paths: Original canonical mirror output family.
            run_id: Original sortable run identity.
            previous: Original pre-refresh models.
            current: Original post-refresh models.
            summaries: Original ordered resource outcomes.

        Returns:
            Original accepted backup directory.
        """
        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(
                    backups.create_live_mirror_backup_manifest,
                    paths,
                    run_id,
                    previous,
                    current,
                    summaries,
                    self.files,
                )
            )
            return await finish_blocking(file_operation)

    async def resource_backup(
        self,
        paths: LibraryAnalysisPaths,
        run_id: str,
        resource: ResourceName,
        target: Path,
        previous: Sequence[LibraryModel],
        current: Sequence[LibraryModel],
        summary: ResourceSyncSummary,
    ) -> Path:
        """Copy only the original requested canonical resource before publication.

        Args:
            paths: Original independent resource workspace.
            run_id: Original sortable run identity.
            resource: Original requested resource.
            target: Original canonical mirror location.
            previous: Original pre-refresh models.
            current: Original post-refresh models.
            summary: Original resource outcome.

        Returns:
            Original accepted backup directory.
        """
        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(
                    backups.create_resource_backup,
                    paths,
                    run_id,
                    resource,
                    target,
                    previous,
                    current,
                    summary,
                    self.files,
                )
            )
            return await finish_blocking(file_operation)

    async def history(
        self, paths: LibraryAnalysisPaths, backup_dir: Path
    ) -> dict[str, object]:
        """Read backed-up history for repeatable publication.

        Args:
            paths: Original independent output family.
            backup_dir: Original accepted backup location.

        Returns:
            Original unmodified pre-analysis history.

        Raises:
            LibrarySyncError: Original manifest or backed-up history is not an object.
        """
        async with blocking_capacity():
            file_operation = asyncio.create_task(
                asyncio.to_thread(
                    backups.pre_analysis_stats_history, paths, backup_dir, self.files
                )
            )
            return await finish_blocking(file_operation)

    def summaries(self, raw: object) -> tuple[ResourceSyncSummary, ...]:
        """Use the original permissive constructor at the unvalidated manifest boundary.

        Args:
            raw: Original unvalidated manifest summary array.

        Returns:
            Original ordered resource summaries.

        Raises:
            TypeError: Original native constructor or iteration rejects malformed input.
        """
        return backups.manifest_summaries(raw)

    def resource_summary(self, raw: object) -> ResourceSyncSummary:
        """Preserve original first-summary indexing and permissive construction.

        Args:
            raw: Original unvalidated manifest summary array.

        Returns:
            Original first recorded resource outcome.

        Raises:
            IndexError: The original summary array is empty.
            TypeError: Original native indexing or construction rejects malformed input.
        """
        return backups.resource_manifest_summary(raw)

    def period(self) -> str:
        """Observe the current statistics history period.

        Returns:
            Current period key.
        """
        return current_stats_history_key()
