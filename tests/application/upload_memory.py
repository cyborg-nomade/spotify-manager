"""Run original upload traces against independently supplied application effects."""

from typing import cast

from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete

from spotify_manager.application.upload_run import UploadActions
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
    from functools import partial

    actions = UploadActions(
        partial(remote, memory),
        materialize,
        manifest,
        partial(commit, memory),
        UploadFailure,
    )
    try:
        return upload(actions, plan)
    except (RuntimeError, OSError) as error:
        return {
            "error": type(error).__name__,
            "message": str(error),
            "cause": type(error.__cause__).__name__ if error.__cause__ else None,
        }
