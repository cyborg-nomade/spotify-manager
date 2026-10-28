"""Observe retained public file seams using named storage methods."""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from spotify_manager.application.library_analysis_publication import AnalysisPublication
from spotify_manager.application.library_analysis_publication import Resources
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.domain.library_analysis_values import ResourceSyncSummary
from spotify_manager.infrastructure.analysis_async_files import AsyncAnalysisStorage
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.library_analysis_publication import AnalysisBackups
from spotify_manager.infrastructure.library_analysis_storage import AnalysisStorage
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.routines import analyse_library as legacy


class ObservedAnalysisFiles(AnalysisStorage):
    """Record file effects at the retained public compatibility boundary."""

    def read(self, path: Path, default: object | None = None) -> object:
        """Read permissive JSON.

        Args:
            path: File location.
            default: Value for a missing file.

        Returns:
            Unvalidated persisted value.
        """
        if default is None:
            return legacy.load_json(path)
        return legacy.load_json(path, default=default)

    def write(self, path: Path, value: object) -> None:
        """Atomically accept JSON.

        Args:
            path: File location.
            value: Complete payload.
        """
        return legacy.write_json_atomic(path, value)

    def models[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a typed model array.

        Args:
            path: Array location.
            model: Validation model.

        Returns:
            Models in stored order.
        """
        return legacy.load_model_list(path, model)

    def staged[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a staging stream, retaining torn-tail recovery.

        Args:
            path: Stream location.
            model: Validation model.

        Returns:
            Accepted models in stored order.
        """
        return legacy.load_models_jsonl(path, model)

    def publish(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Accept a complete model array and publish its managed artifact.

        Args:
            path: Array location.
            models: Complete ordered models.
        """
        return legacy.write_models(path, models)

    def append(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Append models to staging.

        Args:
            path: Stream location.
            models: Ordered accepted models.
        """
        return legacy.append_models_jsonl(path, models)

    def event(
        self, paths: LibraryAnalysisPaths, run_id: str, event: str, **details: object
    ) -> None:
        """Append a timestamped audit event.

        Args:
            paths: Output family.
            run_id: Run identity.
            event: Event name.
            details: Complete audit facts.
        """
        return legacy.append_event(paths, run_id, event, **details)

    def export(self, paths: LibraryAnalysisPaths) -> YourLibraryFile:
        """Read the export authority.

        Args:
            paths: Output family.

        Returns:
            Validated export.
        """
        return legacy.load_your_library(paths)

    def clock(self) -> str:
        """Observe UTC time.

        Returns:
            ISO timestamp.
        """
        return legacy.utc_now()

    def run_id(self) -> str:
        """Observe a fresh run identity.

        Returns:
            Sortable identity.
        """
        return legacy.new_run_id()

    def fingerprint(self, path: Path) -> dict[str, int]:
        """Observe export metadata.

        Args:
            path: Export location.

        Returns:
            Size and modification timestamp.
        """
        return legacy.export_fingerprint(path)

    def export_artists(self, paths: LibraryAnalysisPaths) -> list[YourLibraryArtist]:
        """Read optional export artist candidates.

        Args:
            paths: Output family.

        Returns:
            Latest artists, or an empty list for an absent export.
        """
        return legacy.latest_export_artists(paths)


class RecordedAnalysisBackups(AnalysisBackups):
    """Keep the fixture's original statistics-period observation."""

    def period(self) -> str:
        """Observe the frozen period.

        Returns:
            Original statistics key.
        """
        return legacy.current_stats_history_key()


class ObservedAnalysisBackups(RecordedAnalysisBackups):
    """Observe public backup seams as well as their nested file effects."""

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
            task = asyncio.create_task(
                asyncio.to_thread(
                    legacy.create_backup_manifest,
                    paths,
                    run_id,
                    previous,
                    current,
                    report,
                    summaries,
                )
            )
            return await finish_blocking(task)

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
            task = asyncio.create_task(
                asyncio.to_thread(
                    legacy.create_live_mirror_backup_manifest,
                    paths,
                    run_id,
                    previous,
                    current,
                    summaries,
                )
            )
            return await finish_blocking(task)

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
            task = asyncio.create_task(
                asyncio.to_thread(legacy.pre_analysis_stats_history, paths, backup_dir)
            )
            return await finish_blocking(task)


def observed_analysis_files() -> AsyncAnalysisStorage:
    """Build fixture storage.

    Returns:
        Named storage observing original public seams.
    """
    return AsyncAnalysisStorage(ObservedAnalysisFiles())


def observed_analysis_publication() -> AnalysisPublication:
    """Build fixture undo storage.

    Returns:
        Named publication owner observing original public seams.
    """
    return ObservedAnalysisBackups(observed_analysis_files().source)
