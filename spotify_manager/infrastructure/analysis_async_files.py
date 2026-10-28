"""Await complete analysis file operations while retaining their synchronous formats."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from pydantic import BaseModel

from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.infrastructure.analysis_file_ports import BlockingAnalysisFiles
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.library_analysis_storage import AnalysisStorage
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


@dataclass(frozen=True)
class AsyncAnalysisStorage:
    """Keep one coherent file owner and offload its complete persistence operations.

    Args:
        source: Retained file formats, serialization, publication and time ownership.
    """

    source: BlockingAnalysisFiles = field(default_factory=AnalysisStorage)

    async def read(self, path: Path, default: object | None = None) -> object:
        """Read permissive JSON.

        Args:
            path: File location.
            default: Value for a missing file.

        Returns:
            Unvalidated persisted value.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.read, path, default)
            )
            return await finish_blocking(task)

    async def write(self, path: Path, value: object) -> None:
        """Atomically accept JSON.

        Args:
            path: File location.
            value: Complete payload.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.write, path, value)
            )
            return await finish_blocking(task)

    async def publish_path(self, path: Path, source: str) -> None:
        """Publish an accepted managed artifact.

        Args:
            path: Accepted file.
            source: Provenance label.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.publish_path, path, source)
            )
            return await finish_blocking(task)

    async def models[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a typed model array.

        Args:
            path: Array location.
            model: Validation model.

        Returns:
            Models in stored order.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.models, path, model)
            )
            return await finish_blocking(task)

    async def staged[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a staging stream, retaining torn-tail recovery.

        Args:
            path: Stream location.
            model: Validation model.

        Returns:
            Accepted models in stored order.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.staged, path, model)
            )
            return await finish_blocking(task)

    async def publish(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Accept a complete model array and publish its managed artifact.

        Args:
            path: Array location.
            models: Complete ordered models.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.publish, path, models)
            )
            return await finish_blocking(task)

    async def append(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Append models to staging.

        Args:
            path: Stream location.
            models: Ordered accepted models.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.append, path, models)
            )
            return await finish_blocking(task)

    async def event(
        self, paths: LibraryAnalysisPaths, run_id: str, event: str, **details: object
    ) -> None:
        """Append a timestamped audit event.

        Args:
            paths: Output family.
            run_id: Run identity.
            event: Event name.
            details: Complete audit facts.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.event, paths, run_id, event, **details)
            )
            return await finish_blocking(task)

    async def export(self, paths: LibraryAnalysisPaths) -> YourLibraryFile:
        """Read the export authority.

        Args:
            paths: Output family.

        Returns:
            Validated export.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self.source.export, paths))
            return await finish_blocking(task)

    def clock(self) -> str:
        """Observe UTC time.

        Returns:
            ISO timestamp.
        """
        return self.source.clock()

    def run_id(self) -> str:
        """Observe a fresh run identity.

        Returns:
            Sortable identity.
        """
        return self.source.run_id()

    async def fingerprint(self, path: Path) -> dict[str, int]:
        """Observe export metadata.

        Args:
            path: Export location.

        Returns:
            Size and modification timestamp.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self.source.fingerprint, path))
            return await finish_blocking(task)

    async def reset_staging(self, path: Path) -> None:
        """Replace staging for a fresh run.

        Args:
            path: Staging directory.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.reset_staging, path)
            )
            return await finish_blocking(task)

    async def remove(self, path: Path) -> None:
        """Remove a staging or candidate file if present.

        Args:
            path: File location.
        """
        async with blocking_capacity():
            task = asyncio.create_task(asyncio.to_thread(self.source.remove, path))
            return await finish_blocking(task)

    async def export_artists(
        self, paths: LibraryAnalysisPaths
    ) -> list[YourLibraryArtist]:
        """Read optional export artist candidates.

        Args:
            paths: Output family.

        Returns:
            Latest artists, or an empty list for an absent export.
        """
        async with blocking_capacity():
            task = asyncio.create_task(
                asyncio.to_thread(self.source.export_artists, paths)
            )
            return await finish_blocking(task)

    async def restore(
        self, run_id: str, candidates: list[LibraryAnalysisPaths]
    ) -> tuple[str, ...]:
        """Restore one complete original backup through the file I/O boundary.

        Args:
            run_id: Original backup identity.
            candidates: Original ordered backup families.

        Returns:
            Restored filenames in original manifest order.

        Raises:
            LibrarySyncRestoreError: The backup identity or its files are invalid.
        """
        from spotify_manager.infrastructure.library_analysis_restore import (
            restore_library_sync,
        )

        async with blocking_capacity():
            restoration = asyncio.create_task(
                asyncio.to_thread(restore_library_sync, run_id, candidates, self.source)
            )
            return await finish_blocking(restoration)
