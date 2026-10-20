"""Run original upload traces against independently supplied application effects."""

from dataclasses import dataclass
from typing import cast

from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete

from spotify_manager.application.upload_run import upload
from spotify_manager.application.upload_values import LibraryFilesUploadPlan
from spotify_manager.infrastructure.upload_files import materialize
from spotify_manager.infrastructure.upload_hub import UploadFailure
from spotify_manager.infrastructure.upload_hub import manifest
from tests.support.upload_run import UploadMemory


def remote(memory: UploadMemory, plan: LibraryFilesUploadPlan) -> list[str]:
    """Observe the original listing request through an explicit boundary.

    Args:
        memory: Original remote observation authority.
        plan: Original target repository.

    Returns:
        Original complete remote manifest.
    """
    return memory.list_repo_files(
        repo_id=plan.repo_id, repo_type="space", revision=plan.revision
    )


def commit(
    memory: UploadMemory, plan: LibraryFilesUploadPlan, operations: list[object]
) -> object:
    """Observe the original single commit with its exact operation and naming order.

    Args:
        memory: Original remote observation authority.
        plan: Original source order and revision.
        operations: Original SDK manifest.

    Returns:
        Original commit metadata.
    """
    names = ", ".join(resource.name for resource in plan.resources)
    return memory.create_commit(
        repo_id=plan.repo_id,
        repo_type="space",
        revision=plan.revision,
        operations=cast(list[CommitOperationAdd | CommitOperationDelete], operations),
        commit_message=f"Update library exports: {names}",
    )


def run_upload(plan: LibraryFilesUploadPlan, memory: UploadMemory) -> object:
    """Run the original application sequence without production composition.

    Args:
        plan: Original prepared manifest.
        memory: Recorded original SDK boundary.

    Returns:
        Original result or translated/native failure.
    """
    actions = RecordedUpload(memory)
    try:
        return upload(actions, plan)
    except (RuntimeError, OSError) as error:
        return {
            "error": type(error).__name__,
            "message": str(error),
            "cause": type(error.__cause__).__name__ if error.__cause__ else None,
        }


@dataclass(frozen=True)
class RecordedUpload:
    """Observe upload effects independently of production composition.

    Args:
        memory: Recorded remote authority.
    """

    memory: UploadMemory

    def remote(self, plan: LibraryFilesUploadPlan) -> list[str]:
        """Observe remote at the recorded boundary.

        Args:
            plan: Original upload sources, target and revision.

        Returns:
            Recorded boundary result.
        """
        return remote(self.memory, plan)

    def materialize(self, plan: LibraryFilesUploadPlan) -> None:
        """Observe materialize at the recorded boundary.

        Args:
            plan: Original upload sources, target and revision.
        """
        materialize(plan)

    def manifest(self, plan: LibraryFilesUploadPlan, stale: set[str]) -> list[object]:
        """Observe manifest at the recorded boundary.

        Args:
            plan: Original upload sources, target and revision.
            stale: Obsolete remote fallback names.

        Returns:
            Recorded boundary result.
        """
        return manifest(plan, stale)

    def commit(self, plan: LibraryFilesUploadPlan, operations: list[object]) -> object:
        """Observe commit at the recorded boundary.

        Args:
            plan: Original upload sources, target and revision.
            operations: Ordered SDK commit operations.

        Returns:
            Recorded boundary result.
        """
        return commit(self.memory, plan, operations)

    def failure(self, stage: str, repo: str) -> UploadFailure:
        """Observe failure at the recorded boundary.

        Args:
            stage: Observed listing or commit boundary.
            repo: Target repository identity.

        Returns:
            Recorded boundary result.
        """
        return UploadFailure(stage, repo)
