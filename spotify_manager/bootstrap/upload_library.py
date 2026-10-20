"""Bind upload codecs and caller-owned Hugging Face clients explicitly."""

from typing import cast

from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete
from huggingface_hub import HfApi

from spotify_manager.application.upload_run import Preparation
from spotify_manager.application.upload_run import UploadActions
from spotify_manager.application.upload_values import LibraryFilesUploadPlan
from spotify_manager.infrastructure.upload_resources import ExportPreparation
from spotify_manager.infrastructure.upload_resources import HubUpload


def preparation() -> Preparation:
    """Bind original compatibility seams for export reads and part generation.

    Returns:
        Explicit source preparation dependencies.
    """
    return ExportPreparation()


def actions(api: HfApi | None) -> UploadActions:
    """Select the original truthy client before observing remote state.

    Args:
        api: Original caller-owned optional SDK client.

    Returns:
        Explicit original publication boundaries.
    """
    from spotify_manager.routines import upload_library_files as legacy

    return HubUpload(api or legacy.HfApi())


def _remote(client: HfApi, plan: LibraryFilesUploadPlan) -> list[str]:
    return client.list_repo_files(
        repo_id=plan.repo_id, repo_type="space", revision=plan.revision
    )


def _commit(
    client: HfApi, plan: LibraryFilesUploadPlan, operations: list[object]
) -> object:
    names = ", ".join(resource.name for resource in plan.resources)
    return client.create_commit(
        repo_id=plan.repo_id,
        repo_type="space",
        revision=plan.revision,
        operations=cast(list[CommitOperationAdd | CommitOperationDelete], operations),
        commit_message=f"Update library exports: {names}",
    )
