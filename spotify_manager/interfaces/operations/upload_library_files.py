"""Invoke upload library files use cases for CLI and HTTP features."""

from pathlib import Path as Path

from huggingface_hub import HfApi as HfApi

from spotify_manager.application import upload_run as upload_run
from spotify_manager.application.upload_values import DEFAULT_REPO_ID as DEFAULT_REPO_ID
from spotify_manager.application.upload_values import (
    DEFAULT_REVISION as DEFAULT_REVISION,
)
from spotify_manager.application.upload_values import (
    LASTFM_PART_PREFIX as LASTFM_PART_PREFIX,
)
from spotify_manager.application.upload_values import (
    REMOTE_FILES_DIR as REMOTE_FILES_DIR,
)
from spotify_manager.application.upload_values import GeneratedPart as GeneratedPart
from spotify_manager.application.upload_values import (
    LibraryFilesUploadError as LibraryFilesUploadError,
)
from spotify_manager.application.upload_values import (
    LibraryFilesUploadPlan as LibraryFilesUploadPlan,
)
from spotify_manager.application.upload_values import (
    LibraryFilesUploadResult as LibraryFilesUploadResult,
)
from spotify_manager.application.upload_values import UploadResource as UploadResource
from spotify_manager.bootstrap import upload_library as upload_library
from spotify_manager.routines.upload_library_files import FILES_DIR as FILES_DIR


def prepare_library_files_upload(
    *,
    include_your_library: bool = True,
    include_lastfm: bool = True,
    repo_id: str = DEFAULT_REPO_ID,
    revision: str = DEFAULT_REVISION,
    files_dir: Path = FILES_DIR,
) -> LibraryFilesUploadPlan:
    """Validate selected exports and prepare deterministic Last.fm parts.

    Args:
        include_your_library: Select the original Spotify export.
        include_lastfm: Select Last.fm export and compressed fallback parts.
        repo_id: Original target Space repository identity.
        revision: Original target repository revision.
        files_dir: Original local managed export directory.

    Returns:
        Original prepare library files upload result.
    """
    return upload_run.prepare(
        upload_library.preparation(),
        files_dir,
        include_your_library,
        include_lastfm,
        repo_id,
        revision,
    )


def upload_library_files(
    plan: LibraryFilesUploadPlan, *, api: HfApi | None = None
) -> LibraryFilesUploadResult:
    """Upload the plan to the configured HF Space in one commit.

    Args:
        plan: Original prepared source and generated-part manifest.
        api: Original optional caller-owned Hugging Face client.

    Returns:
        Original upload library files result.
    """
    return upload_run.upload(upload_library.actions(api), plan)
