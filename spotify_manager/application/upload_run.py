"""Original preparation and ordered remote/local upload stages."""

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


class Preparation(Protocol):
    """Read selected exports and encode deterministic fallback parts."""

    def read(self, path: Path, key: str) -> tuple[bytes, int]:
        """Read and shallowly validate an export.

        Args:
            path: Export location.
            key: Required top-level array.

        Returns:
            Original bytes and row count.
        """
        ...

    def parts(self, path: Path, content: bytes) -> tuple[GeneratedPart, ...]:
        """Encode history fallback parts without publishing files.

        Args:
            path: Original history location.
            content: Accepted export bytes.

        Returns:
            Deterministic parts.
        """
        ...


class UploadActions(Protocol):
    """Read remote state and publish local and remote upload artifacts."""

    def remote(self, plan: LibraryFilesUploadPlan) -> list[str]:
        """Read complete remote file names.

        Args:
            plan: Target repository and revision.

        Returns:
            Remote file names.
        """
        ...

    def materialize(self, plan: LibraryFilesUploadPlan) -> None:
        """Accept local fallback parts and remove obsolete local parts.

        Args:
            plan: Complete upload plan.
        """
        ...

    def manifest(self, plan: LibraryFilesUploadPlan, stale: set[str]) -> list[object]:
        """Encode ordered SDK commit operations.

        Args:
            plan: Complete upload plan.
            stale: Obsolete remote fallbacks.

        Returns:
            Ordered operations.
        """
        ...

    def commit(self, plan: LibraryFilesUploadPlan, operations: list[object]) -> object:
        """Accept one remote commit.

        Args:
            plan: Target revision and source order.
            operations: Ordered SDK operations.

        Returns:
            Commit metadata.
        """
        ...

    def failure(self, stage: str, repo: str) -> FailureScope:
        """Open the transport error translation scope.

        Args:
            stage: Listing or commit boundary.
            repo: Target repository.

        Returns:
            Error translation context.
        """
        ...


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
