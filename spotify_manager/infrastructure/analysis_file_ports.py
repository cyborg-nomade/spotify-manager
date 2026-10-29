"""Retained synchronous analysis storage used only below bounded async edges."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


class BlockingAnalysisFiles(Protocol):
    """Store analysis checkpoints, model arrays, staging streams and audit events."""

    def read(self, path: Path, default: object | None = None) -> object:
        """Read permissive JSON.

        Args:
            path: File location.
            default: Value for a missing file.

        Returns:
            Unvalidated persisted value.
        """
        ...

    def write(self, path: Path, value: object) -> None:
        """Atomically accept JSON.

        Args:
            path: File location.
            value: Complete payload.
        """
        ...

    def publish_path(self, path: Path, source: str) -> None:
        """Publish an accepted managed artifact.

        Args:
            path: Accepted file.
            source: Provenance label.
        """
        ...

    def models[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a typed model array.

        Args:
            path: Array location.
            model: Validation model.

        Returns:
            Models in stored order.
        """
        ...

    def staged[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a staging stream, retaining torn-tail recovery.

        Args:
            path: Stream location.
            model: Validation model.

        Returns:
            Accepted models in stored order.
        """
        ...

    def publish(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Accept a complete model array and publish its managed artifact.

        Args:
            path: Array location.
            models: Complete ordered models.
        """
        ...

    def append(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Append models to staging.

        Args:
            path: Stream location.
            models: Ordered accepted models.
        """
        ...

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
        ...

    def export(self, paths: LibraryAnalysisPaths) -> YourLibraryFile:
        """Read the export authority.

        Args:
            paths: Output family.

        Returns:
            Validated export.
        """
        ...

    def clock(self) -> str:
        """Observe UTC time.

        Returns:
            ISO timestamp.
        """
        ...

    def run_id(self) -> str:
        """Observe a fresh run identity.

        Returns:
            Sortable identity.
        """
        ...

    def fingerprint(self, path: Path) -> dict[str, int]:
        """Observe export metadata.

        Args:
            path: Export location.

        Returns:
            Size and modification timestamp.
        """
        ...

    def reset_staging(self, path: Path) -> None:
        """Replace staging for a fresh run.

        Args:
            path: Staging directory.
        """
        ...

    def remove(self, path: Path) -> None:
        """Remove a staging or candidate file if present.

        Args:
            path: File location.
        """
        ...

    def export_artists(self, paths: LibraryAnalysisPaths) -> list[YourLibraryArtist]:
        """Read optional export artist candidates.

        Args:
            paths: Output family.

        Returns:
            Latest artists, or an empty list for an absent export.
        """
        ...
