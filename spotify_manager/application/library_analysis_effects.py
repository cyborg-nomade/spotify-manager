"""Explicit file, catalog, retry and interaction boundaries for library analysis."""

from collections.abc import Callable
from collections.abc import Sequence
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


class ReadJson(Protocol):
    """Read unvalidated legacy JSON at an external storage boundary."""

    def __call__(self, path: Path, default: object | None = None) -> object:
        """Read original persisted facts without applying new validation.

        Args:
            path: Original file location.
            default: Original missing-file result.

        Returns:
            Original unvalidated JSON value.
        """
        ...


class ReadModels(Protocol):
    """Read a complete original model array or staging stream."""

    def __call__[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read original typed model facts.

        Args:
            path: Original complete file location.
            model: Original tolerant model constructor.

        Returns:
            Complete original models in stored order.
        """
        ...


class AnalysisEvent(Protocol):
    """Append original timestamped analysis audit details."""

    def __call__(
        self, paths: LibraryAnalysisPaths, run_id: str, event: str, **details: object
    ) -> None:
        """Accept the original ordered audit boundary.

        Args:
            paths: Original output family.
            run_id: Original sortable run identity.
            event: Original event name.
            details: Original complete event facts.
        """
        ...


class RetryOperation(Protocol):
    """Execute the original bounded synchronous retry boundary."""

    def __call__[T](
        self,
        operation: Callable[[], T],
        description: str,
        max_attempts: int | None = None,
    ) -> T:
        """Read original live facts using the configured retry policy.

        Args:
            operation: Original complete request.
            description: Original visible operation label.
            max_attempts: Original optional attempt limit.

        Returns:
            Original accepted response.
        """
        ...


class OffsetRead(Protocol):
    """Read original saved album or track pages using explicit offsets."""

    def __call__(self, *, limit: int, offset: int) -> object:
        """Read one original live page.

        Args:
            limit: Original page size.
            offset: Original raw-row offset.

        Returns:
            Original unvalidated Spotify response.
        """
        ...


@dataclass(frozen=True)
class AnalysisFiles:
    """Bind original reads, accepted publications, audit and clock observations.

    Args:
        read: Original permissive JSON read.
        write: Original atomic JSON write.
        models: Original model-array read.
        staged: Original JSON-lines read, including torn-tail semantics.
        publish: Original model-array write and managed-file publication.
        append: Original JSON-lines append.
        event: Original timestamped audit append.
        export: Original validated export read.
        clock: Original UTC timestamp observation.
        run_id: Original fresh run identity observation.
        fingerprint: Original export stat observation.
        reset_staging: Original destructive staging reset for a fresh run.
        remove: Original candidate/staging removal boundary.
        export_artists: Original optional latest export candidate read.
    """

    read: ReadJson
    write: Callable[[Path, object], None]
    models: ReadModels
    staged: ReadModels
    publish: Callable[[Path, Sequence[BaseModel]], None]
    append: Callable[[Path, Sequence[BaseModel]], None]
    event: AnalysisEvent
    export: Callable[[LibraryAnalysisPaths], YourLibraryFile]
    clock: Callable[[], str]
    run_id: Callable[[], str]
    fingerprint: Callable[[Path], dict[str, int]]
    reset_staging: Callable[[Path], None]
    remove: Callable[[Path], None]
    export_artists: Callable[[LibraryAnalysisPaths], list[YourLibraryArtist]]


@dataclass(frozen=True)
class AnalysisCatalog:
    """Supply original page reads and tolerant record conversion.

    Args:
        offset: Select the original offset method at its original read boundary.
        artists: Original followed-artists scan, including immediate 502 fallback.
        reconcile_artists: Original unbounded followed-artists reconciliation read.
        following: Original artist-follow verification batch.
        album: Original tolerant saved-album conversion.
        track: Original tolerant saved-track conversion.
        artist: Original tolerant artist conversion.
        items: Original offset-page shape validation.
        artist_items: Original artist-page shape validation.
    """

    offset: Callable[[ResourceName, bool], OffsetRead]
    artists: Callable[[str | None], object]
    reconcile_artists: Callable[[str | None], object]
    following: Callable[[list[str]], object]
    album: Callable[[object], LibraryModel | None]
    track: Callable[[object], LibraryModel | None]
    artist: Callable[[object], LibraryModel | None]
    items: Callable[[object, ResourceName], list[object]]
    artist_items: Callable[[object], tuple[list[object], dict[str, object]]]


@dataclass(frozen=True)
class AnalysisSession:
    """Own one original mutable checkpoint and its ordered external boundaries.

    Args:
        paths: Original independent output family.
        checkpoint: Original mutable durable progress mapping.
        files: Original storage and clock boundaries.
        catalog: Original live catalog and conversion boundaries.
        request: Original invocation-scoped retry boundary.
        echo: Original presenter.
        progress: Original optional resource progress callback.
        cancelled: Original optional cancellation observation.
    """

    paths: LibraryAnalysisPaths
    checkpoint: Checkpoint
    files: AnalysisFiles
    catalog: AnalysisCatalog
    request: RetryOperation
    echo: Echo
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
            self.progress(resource, done, total, label)

    def check_cancel(self) -> None:
        """Observe original cancellation at a durable boundary.

        Raises:
            LibraryAnalysisCancelledError: The original caller requested a pause.
        """
        if self.cancelled is not None and self.cancelled():
            raise LibraryAnalysisCancelledError("Live analysis paused by request.")
