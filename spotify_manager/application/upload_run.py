"""Original preparation and ordered remote/local upload stages."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Protocol

from spotify_manager.application.upload_values import LASTFM_BINARY_PART_PREFIX
from spotify_manager.application.upload_values import LASTFM_COMPRESSED_FILENAME
from spotify_manager.application.upload_values import LASTFM_FILENAME
from spotify_manager.application.upload_values import LASTFM_PART_PREFIX
from spotify_manager.application.upload_values import REMOTE_FILES_DIR
from spotify_manager.application.upload_values import YOUR_LIBRARY_FILENAME
from spotify_manager.application.upload_values import GeneratedPart
from spotify_manager.application.upload_values import LibraryFilesUploadPlan
from spotify_manager.application.upload_values import LibraryFilesUploadResult
from spotify_manager.application.upload_values import UploadResource
from spotify_manager.domain.upload_manifest import LibraryFilesUploadError
from spotify_manager.domain.upload_manifest import stale_parts


class FailureScope(Protocol):
    """Retain original ordinary-error translation at an external boundary."""

    def __enter__(self) -> None:
        """Enter the original translated boundary."""
        ...

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """Translate original ordinary failures and propagate process control.

        Args:
            kind: Original failure class.
            error: Original raised failure.
            traceback: Original traceback.

        Returns:
            False unless the scope raises the original translated error.
        """
        ...


@dataclass(frozen=True)
class Preparation:
    """Supply original shallow export validation and deterministic part encoding.

    Args:
        read: Original selected export read.
        parts: Original inline part generation.
    """

    read: Callable[[Path, str], tuple[bytes, int]]
    parts: Callable[[Path, bytes], tuple[GeneratedPart, ...]]


@dataclass(frozen=True)
class UploadActions:
    """Supply original remote and local publication boundaries.

    Args:
        remote: Complete remote file read.
        materialize: Original local publication and cleanup.
        manifest: Original ordered SDK operation construction.
        commit: Original single remote commit.
        failure: Original boundary error translation.
    """

    remote: Callable[[LibraryFilesUploadPlan], list[str]]
    materialize: Callable[[LibraryFilesUploadPlan], None]
    manifest: Callable[[LibraryFilesUploadPlan, set[str]], list[object]]
    commit: Callable[[LibraryFilesUploadPlan, list[object]], object]
    failure: Callable[[str, str], FailureScope]


def prepare(
    deps: Preparation,
    directory: Path,
    include_library: bool,
    include_lastfm: bool,
    repo: str,
    revision: str,
) -> LibraryFilesUploadPlan:
    """Prepare selected sources in original order without materializing parts.

    Args:
        deps: Original source and encoding observations.
        directory: Original managed directory.
        include_library: Select the Spotify export.
        include_lastfm: Select the Last.fm export.
        repo: Original repository identity.
        revision: Original target revision.

    Returns:
        Original validated manifest.

    Raises:
        LibraryFilesUploadError: No source is selected or validation fails.
    """
    if not include_library and not include_lastfm:
        raise LibraryFilesUploadError("Select at least one export to upload.")
    resources: list[UploadResource] = []
    parts: tuple[GeneratedPart, ...] = ()
    if include_library:
        resource, _ = _prepare_resource(
            deps, directory, YOUR_LIBRARY_FILENAME, "tracks"
        )
        resources.append(resource)
    if include_lastfm:
        resource, content = _prepare_resource(
            deps, directory, LASTFM_FILENAME, "scrobbles"
        )
        resources.append(resource)
        parts = deps.parts(resource.local_path, content)
    return LibraryFilesUploadPlan(repo, revision, tuple(resources), parts)


def _prepare_resource(
    deps: Preparation, directory: Path, name: str, key: str
) -> tuple[UploadResource, bytes]:
    path = directory / name
    content, count = deps.read(path, key)
    resource = UploadResource(
        name, path, f"{REMOTE_FILES_DIR}/{name}", count, len(content)
    )
    return resource, content


def upload(
    deps: UploadActions, plan: LibraryFilesUploadPlan
) -> LibraryFilesUploadResult:
    """Observe remote files before local publication and one ordered commit.

    Args:
        deps: Original explicitly supplied publication boundaries.
        plan: Original validated manifest.

    Returns:
        Original accepted commit summary.

    Raises:
        LibraryFilesUploadError: Original listing, publication or commit fails.
    """
    with deps.failure("list", plan.repo_id):
        remote = set(deps.remote(plan))
    desired = {part.path_in_repo for part in plan.lastfm_parts}
    stale = stale_parts(
        remote,
        desired,
        f"{REMOTE_FILES_DIR}/{LASTFM_COMPRESSED_FILENAME}",
        f"{REMOTE_FILES_DIR}/{LASTFM_BINARY_PART_PREFIX}",
        f"{REMOTE_FILES_DIR}/{LASTFM_PART_PREFIX}",
    )
    deps.materialize(plan)
    operations = deps.manifest(plan, stale)
    with deps.failure("commit", plan.repo_id):
        commit = deps.commit(plan, operations)
    return _upload_result(plan, stale, commit)


def _upload_result(
    plan: LibraryFilesUploadPlan, stale: set[str], commit: object
) -> LibraryFilesUploadResult:
    url = getattr(commit, "commit_url", None)
    if not isinstance(url, str):
        raise LibraryFilesUploadError(
            "HF accepted the commit but did not return a commit URL."
        )
    return LibraryFilesUploadResult(
        url, plan.upload_file_count, len(stale), plan.upload_size_bytes
    )
