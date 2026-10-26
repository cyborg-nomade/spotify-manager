"""Explicit file, catalog, retry and interaction boundaries for library analysis."""

from collections.abc import Iterator
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from spotify_manager.application.library_analysis_values import CancelCheck
from spotify_manager.application.library_analysis_values import Checkpoint
from spotify_manager.application.library_analysis_values import Echo
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.application.library_analysis_values import ProgressCallback
from spotify_manager.domain.library_analysis_values import LibraryAnalysisCancelledError
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


class RetryOperation(Protocol):
    """Execute bounded synchronous requests with the configured retry policy."""

    def attempts(
        self, description: str, max_attempts: int | None = None
    ) -> Iterator[AbstractContextManager[None]]:
        """Provide scopes for the directly visible request.

        Args:
            description: Original operation description.
            max_attempts: Original optional attempt limit.

        Returns:
            Original bounded or unbounded attempt scopes.
        """
        ...


class OffsetRead(Protocol):
    """Read saved-resource pages from one selected transport endpoint."""

    def read(self, *, limit: int, offset: int) -> object:
        """Read one page.

        Args:
            limit: Page size.
            offset: Raw row offset.

        Returns:
            Unvalidated transport response.
        """
        ...


class AnalysisFiles(Protocol):
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


class AnalysisCatalog(Protocol):
    """Read live library pages and decode their transport records."""

    def offset(self, resource: ResourceName, initial: bool) -> OffsetRead:
        """Select a saved-resource reader at the scan boundary.

        Args:
            resource: Saved resource.
            initial: Whether this is the initial scan.

        Returns:
            Selected page reader.
        """
        ...

    def artists(self, after: str | None) -> object:
        """Read followed artists with endpoint fallback.

        Args:
            after: Stored cursor.

        Returns:
            Unvalidated page.
        """
        ...

    def reconcile_artists(self, after: str | None) -> object:
        """Read a reconciliation page.

        Args:
            after: Current cursor.

        Returns:
            Unvalidated page.
        """
        ...

    def following(self, identities: list[str]) -> object:
        """Verify live follows.

        Args:
            identities: Ordered verification batch.

        Returns:
            Unvalidated follow statuses.
        """
        ...

    def convert(self, row: object, resource: ResourceName) -> LibraryModel | None:
        """Decode a saved-resource row.

        Args:
            row: Raw transport row.
            resource: Resource whose record format applies.

        Returns:
            Model, or none for an unusable row.
        """
        ...

    def items(self, page: object, resource: ResourceName) -> list[object]:
        """Validate an offset page envelope.

        Args:
            page: Raw response.
            resource: Active resource.

        Returns:
            Complete raw rows.
        """
        ...

    def artist_items(self, page: object) -> tuple[list[object], dict[str, object]]:
        """Validate a cursor page envelope.

        Args:
            page: Raw response.

        Returns:
            Raw rows and cursor envelope.
        """
        ...


@dataclass(frozen=True)
class AnalysisSession:
    """Own one original mutable checkpoint and its ordered external boundaries.

    Args:
        paths: Original independent output family.
        checkpoint: Original mutable durable progress mapping.
        files: Original storage and clock boundaries.
        catalog: Original live catalog and conversion boundaries.
        request: Original invocation-scoped retry boundary.
        output: Original presenter.
        progress: Original optional resource progress callback.
        cancelled: Original optional cancellation observation.
    """

    paths: LibraryAnalysisPaths
    checkpoint: Checkpoint
    files: AnalysisFiles
    catalog: AnalysisCatalog
    request: RetryOperation
    output: Echo
    progress: ProgressCallback | None
    cancelled: CancelCheck | None

    def save(self) -> None:
        """Accept the original atomic checkpoint write."""
        self.files.write(self.paths.checkpoint, self.checkpoint)

    def event(self, name: str, **details: object) -> None:
        """Append original run-scoped audit facts.

        Args:
            name: Original audit event.
            details: Original complete event facts.
        """
        self.files.event(self.paths, str(self.checkpoint["run_id"]), name, **details)

    def notify(
        self, resource: ResourceName, done: int, total: int | None, label: str
    ) -> None:
        """Deliver progress with the original callback truthiness semantics.

        Args:
            resource: Original active resource.
            done: Original accepted count or raw-row offset.
            total: Original reported total or none.
            label: Original visible stage label.
        """
        if self.progress:
            self.progress.progress(resource, done, total, label)

    def check_cancel(self) -> None:
        """Observe original cancellation at a durable boundary.

        Raises:
            LibraryAnalysisCancelledError: The original caller requested a pause.
        """
        if self.cancelled is not None and self.cancelled.is_set():
            raise LibraryAnalysisCancelledError("Live analysis paused by request.")
