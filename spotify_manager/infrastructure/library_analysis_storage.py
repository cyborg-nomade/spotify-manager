"""Filesystem storage for analysis arrays, staging, checkpoints and audit."""

from collections.abc import Sequence
from datetime import UTC
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.bootstrap.library_data import publish_managed_path
from spotify_manager.infrastructure import library_analysis_files as files
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


class AnalysisStorage:
    """Persist analysis facts with the existing formats and publication order."""

    def read(self, path: Path, default: object | None = None) -> object:
        """Read permissive JSON.

        Args:
            path: File location.
            default: Value for a missing file.

        Returns:
            Unvalidated persisted value.
        """
        return files.load_json(path, default)

    def write(self, path: Path, value: object) -> None:
        """Atomically accept JSON.

        Args:
            path: File location.
            value: Complete payload.
        """
        return files.write_json_atomic(path, value)

    def models[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a typed model array.

        Args:
            path: Array location.
            model: Validation model.

        Returns:
            Models in stored order.
        """
        return files.load_model_list(path, model, storage=self)

    def staged[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read a staging stream, retaining torn-tail recovery.

        Args:
            path: Stream location.
            model: Validation model.

        Returns:
            Accepted models in stored order.
        """
        return files.load_models_jsonl(path, model)

    def publish(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Accept a complete model array and publish its managed artifact.

        Args:
            path: Array location.
            models: Complete ordered models.
        """
        return files.write_models(path, models, storage=self)

    def append(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Append models to staging.

        Args:
            path: Stream location.
            models: Ordered accepted models.
        """
        return files.append_models_jsonl(path, models)

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
        return files.append_event(self, paths, run_id, event, **details)

    def export(self, paths: LibraryAnalysisPaths) -> YourLibraryFile:
        """Read the export authority.

        Args:
            paths: Output family.

        Returns:
            Validated export.
        """
        return files.load_your_library(paths, storage=self)

    def clock(self) -> str:
        """Observe UTC time.

        Returns:
            ISO timestamp.
        """
        return datetime.now(UTC).isoformat()

    def run_id(self) -> str:
        """Observe a fresh run identity.

        Returns:
            Sortable identity.
        """
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")

    def fingerprint(self, path: Path) -> dict[str, int]:
        """Observe export metadata.

        Args:
            path: Export location.

        Returns:
            Size and modification timestamp.
        """
        return files.export_fingerprint(path)

    def reset_staging(self, path: Path) -> None:
        """Replace staging for a fresh run.

        Args:
            path: Staging directory.
        """
        return files.reset_staging(path)

    def remove(self, path: Path) -> None:
        """Remove a staging or candidate file if present.

        Args:
            path: File location.
        """
        return files.remove(path)

    def export_artists(self, paths: LibraryAnalysisPaths) -> list[YourLibraryArtist]:
        """Read optional export artist candidates.

        Args:
            paths: Output family.

        Returns:
            Latest artists, or an empty list for an absent export.
        """
        return files.latest_export_artists(paths, self)

    def publish_path(self, path: Path, source: str) -> None:
        """Publish an accepted managed artifact.

        Args:
            path: Accepted file.
            source: Provenance label.
        """
        publish_managed_path(path, source=source)
