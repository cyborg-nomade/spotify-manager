"""Original Hugging Face manifest construction and boundary error translation."""

from types import TracebackType
from typing import Literal

from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete

from spotify_manager.application.upload_values import LibraryFilesUploadPlan
from spotify_manager.domain.upload_manifest import LibraryFilesUploadError


class UploadFailure:
    """Translate original ordinary SDK failures without catching process control.

    Args:
        stage: Original listing or commit boundary.
        repo: Original repository used in visible error messages.
    """

    def __init__(self, stage: str, repo: str) -> None:
        """Retain the original error context.

        Args:
            stage: Original translated boundary.
            repo: Original target repository.
        """
        self.stage = stage
        self.repo = repo

    def __enter__(self) -> None:
        """Enter the original translated boundary."""

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        """Preserve original error text, explicit cause and process-control propagation.

        Args:
            kind: Original failure class.
            error: Original raised failure.
            traceback: Original traceback.

        Returns:
            False when there is no ordinary failure.

        Raises:
            LibraryFilesUploadError: The original boundary raised an ordinary error.
        """
        if not isinstance(error, Exception):
            return False
        if self.stage == "list":
            message = (
                f"Could not read files from HF Space '{self.repo}': {error}. "
                "Confirm `hf auth login` and your access to the Space."
            )
        else:
            message = (
                f"HF upload to '{self.repo}' failed: {error}. "
                "The local fallback parts are current, so the command can be retried."
            )
        raise LibraryFilesUploadError(message) from error


def manifest(plan: LibraryFilesUploadPlan, stale: set[str]) -> list[object]:
    """Build original resource, inline-part and sorted-delete operations.

    Args:
        plan: Original source and generated part order.
        stale: Original obsolete remote fallbacks.

    Returns:
        Original ordered SDK commit operations.
    """
    operations: list[object] = []
    for resource in plan.resources:
        operations.append(
            CommitOperationAdd(
                path_in_repo=resource.path_in_repo, path_or_fileobj=resource.local_path
            )
        )
    for part in plan.lastfm_parts:
        operations.append(
            CommitOperationAdd(
                path_in_repo=part.path_in_repo, path_or_fileobj=part.content
            )
        )
    for path in sorted(stale):
        operations.append(CommitOperationDelete(path_in_repo=path))
    return operations
