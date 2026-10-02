"""Typed memory boundaries for unusual durable analysis states and malformed facts."""

from collections.abc import Callable
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from spotify_manager.application.library_analysis_checkpoint import new_checkpoint
from spotify_manager.application.library_analysis_effects import AnalysisCatalog
from spotify_manager.application.library_analysis_effects import AnalysisFiles
from spotify_manager.application.library_analysis_effects import AnalysisSession
from spotify_manager.application.library_analysis_effects import OffsetRead
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


@dataclass
class AnalysisMemory:
    """Accept original semantic reads and writes without SDKs or physical files.

    Args:
        raw: Original permissive JSON facts by complete path.
        arrays: Original stored model facts by complete path.
        pages: Original next live page envelopes.
        follow_response: Original unvalidated candidate follow response.
        effects: Complete accepted semantic observations.
    """

    raw: dict[Path, object] = field(default_factory=dict)
    arrays: dict[Path, list[BaseModel]] = field(default_factory=dict)
    pages: list[dict[str, object]] = field(default_factory=list)
    follow_response: object = ()
    effects: list[tuple[str, object]] = field(default_factory=list)

    def read(self, path: Path, default: object | None = None) -> object:
        """Read original permissive memory JSON facts.

        Args:
            path: Original complete file location.
            default: Original absent-file result.

        Returns:
            Original stored unvalidated value.
        """
        self.effects.append(("read", path))
        return self.raw.get(path, default)

    def write(self, path: Path, value: object) -> None:
        """Accept an independent durable snapshot of original mutable values.

        Args:
            path: Original complete target location.
            value: Original complete payload.
        """
        self.effects.append(("write", path))
        self.raw[path] = deepcopy(value)

    def models[T: BaseModel](self, path: Path, model: type[T]) -> list[T]:
        """Read original typed model facts in stored encounter order.

        Args:
            path: Original complete model/staging location.
            model: Original expected model type.

        Returns:
            Independent list retaining original model values.
        """
        self.effects.append(("models", path))
        return cast(list[T], list(self.arrays.get(path, [])))

    def publish(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Accept original complete model-array publication.

        Args:
            path: Original complete target location.
            models: Original ordered complete models.
        """
        self.effects.append(("publish", path))
        self.arrays[path] = list(models)

    def append(self, path: Path, models: Sequence[BaseModel]) -> None:
        """Accept original model staging in encounter order.

        Args:
            path: Original complete staging location.
            models: Original ordered accepted rows.
        """
        self.effects.append(("append", (path, list(models))))
        self.arrays.setdefault(path, []).extend(models)

    def event(
        self, paths: LibraryAnalysisPaths, run_id: str, event: str, **details: object
    ) -> None:
        """Observe original durable audit classification and details.

        Args:
            paths: Original output family.
            run_id: Original sortable run identity.
            event: Original event name.
            details: Original complete audit facts.
        """
        self.effects.append((event, deepcopy(details)))

    def export(self, paths: LibraryAnalysisPaths) -> YourLibraryFile:
        """Supply an empty original export for independent state-boundary tests.

        Args:
            paths: Original independent output family.

        Returns:
            Original empty export facts.
        """
        return YourLibraryFile(albums=[], tracks=[], artists=[])

    def remove(self, path: Path) -> None:
        """Accept original candidate/staging removal.

        Args:
            path: Original complete target location.
        """
        self.effects.append(("remove", path))
        self.raw.pop(path, None)
        self.arrays.pop(path, None)

    def reset(self, path: Path) -> None:
        """Observe original fresh-staging reset.

        Args:
            path: Original complete staging location.
        """
        self.effects.append(("reset", path))

    def echo(self, text: str) -> None:
        """Observe original visible output.

        Args:
            text: Original complete message.
        """
        self.effects.append(("echo", text))

    def progress(
        self, resource: ResourceName, done: int, total: int | None, label: str
    ) -> None:
        """Observe original resource-level progress.

        Args:
            resource: Original active resource.
            done: Original current accepted count.
            total: Original reported total.
            label: Original visible stage.
        """
        self.effects.append(("progress", (resource, done, total, label)))

    def offset(self, resource: ResourceName, initial: bool) -> OffsetRead:
        """Select original in-memory offset facts.

        Args:
            resource: Original saved-resource identity.
            initial: Original monotonic-versus-reconciliation phase.

        Returns:
            Original memory offset page reader.
        """
        return self.offset_page

    def offset_page(self, *, limit: int, offset: int) -> object:
        """Read the original next offset page.

        Args:
            limit: Original page size.
            offset: Original raw-row offset.

        Returns:
            Original next page envelope.
        """
        self.effects.append(("offset", (limit, offset)))
        return self.pages.pop(0)

    def cursor(self, after: str | None) -> object:
        """Read original next cursor facts.

        Args:
            after: Original current cursor.

        Returns:
            Original next artist page envelope.
        """
        self.effects.append(("cursor", after))
        return {"artists": self.pages.pop(0)}

    def following(self, identities: list[str]) -> object:
        """Read original unvalidated candidate follow facts.

        Args:
            identities: Original complete verification batch.

        Returns:
            Original follow status response.
        """
        self.effects.append(("following", identities))
        return self.follow_response


def _clock() -> str:
    return "2026-09-24T12:00:00+00:00"


def _run_id() -> str:
    return "memory-run"


def _fingerprint(path: Path) -> dict[str, int]:
    return {"size": 1, "mtime_ns": 99}


def _export_artists(paths: LibraryAnalysisPaths) -> list[YourLibraryArtist]:
    return []


def _convert(raw: object) -> LibraryModel | None:
    return cast(LibraryModel, raw) if isinstance(raw, BaseModel) else None


def _items(raw: object, resource: ResourceName) -> list[object]:
    return cast(list[object], cast(dict[str, object], raw)["items"])


def _artist_items(raw: object) -> tuple[list[object], dict[str, object]]:
    page = cast(dict[str, dict[str, object]], raw)["artists"]
    return cast(list[object], page["items"]), page


def _request[T](
    operation: Callable[[], T], description: str, max_attempts: int | None = None
) -> T:
    return operation()


def memory_session(
    memory: AnalysisMemory, root: Path, progress: bool = True
) -> AnalysisSession:
    """Construct a complete typed use-case session from memory authority.

    Args:
        memory: Original fake authority and accepted effects.
        root: Original independent output path family.
        progress: Whether to attach the original optional presenter.

    Returns:
        Independently injected session without production bootstrap or SDKs.
    """
    paths = LibraryAnalysisPaths.for_files_dir(root, "mirrors")
    files = AnalysisFiles(
        memory.read,
        memory.write,
        memory.models,
        memory.models,
        memory.publish,
        memory.append,
        memory.event,
        memory.export,
        _clock,
        _run_id,
        _fingerprint,
        memory.reset,
        memory.remove,
        _export_artists,
    )
    catalog = AnalysisCatalog(
        memory.offset,
        memory.cursor,
        memory.cursor,
        memory.following,
        _convert,
        _convert,
        _convert,
        _items,
        _artist_items,
    )
    checkpoint = new_checkpoint(files, paths)
    return AnalysisSession(
        paths,
        checkpoint,
        files,
        catalog,
        _request,
        memory.echo,
        memory.progress if progress else None,
        None,
    )
