"""Bind upload codecs and caller-owned Hugging Face clients explicitly."""

from functools import partial
from pathlib import Path
from typing import cast

from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete
from huggingface_hub import HfApi

from spotify_manager.application.upload_run import Preparation
from spotify_manager.application.upload_run import UploadActions
from spotify_manager.application.upload_values import LibraryFilesUploadPlan
from spotify_manager.infrastructure.upload_hub import UploadFailure
from spotify_manager.infrastructure.upload_hub import manifest


def preparation() -> Preparation:
    """Bind original compatibility seams for export reads and part generation.

    Returns:
        Explicit source preparation dependencies.
    """
    from spotify_manager.routines.upload_library_files import _build_lastfm_parts

    return Preparation(_read_export, _build_lastfm_parts)


def _read_export(path: Path, key: str) -> tuple[bytes, int]:
    from spotify_manager.routines.upload_library_files import _load_and_validate_export

    return _load_and_validate_export(path, expected_list_key=key)


def actions(api: HfApi | None) -> UploadActions:
    """Select the original truthy client before observing remote state.

    Args:
        api: Original caller-owned optional SDK client.

    Returns:
        Explicit original publication boundaries.
    """
    from spotify_manager.routines import upload_library_files as legacy
    from spotify_manager.routines.upload_library_files import materialize_lastfm_parts

    client = api or legacy.HfApi()
    return UploadActions(
        partial(_remote, client),
        materialize_lastfm_parts,
        manifest,
        partial(_commit, client),
        UploadFailure,
    )


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
