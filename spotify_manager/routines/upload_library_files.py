"""Compatibility entry points for original library-export preparation and upload."""

from pathlib import Path

from huggingface_hub import HfApi as HfApi

from spotify_manager.application.upload_values import DEFAULT_REPO_ID as DEFAULT_REPO_ID
from spotify_manager.application.upload_values import (
    DEFAULT_REVISION as DEFAULT_REVISION,
)
from spotify_manager.application.upload_values import (
    LASTFM_BINARY_PART_PREFIX as LASTFM_BINARY_PART_PREFIX,
)
from spotify_manager.application.upload_values import (
    LASTFM_COMPRESSED_FILENAME as LASTFM_COMPRESSED_FILENAME,
)
from spotify_manager.application.upload_values import LASTFM_FILENAME as LASTFM_FILENAME
from spotify_manager.application.upload_values import (
    LASTFM_PART_PREFIX as LASTFM_PART_PREFIX,
)
from spotify_manager.application.upload_values import (
    LASTFM_PART_SIZE as LASTFM_PART_SIZE,
)
from spotify_manager.application.upload_values import (
    REMOTE_FILES_DIR as REMOTE_FILES_DIR,
)
from spotify_manager.application.upload_values import (
    YOUR_LIBRARY_FILENAME as YOUR_LIBRARY_FILENAME,
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
from spotify_manager.domain.upload_manifest import part_suffix
from spotify_manager.infrastructure import upload_files


FILES_DIR = Path(__file__).resolve().parent.parent / "files"


def _remote_path(filename: str) -> str:
    return f"{REMOTE_FILES_DIR}/{filename}"


def _load_and_validate_export(
    path: Path, *, expected_list_key: str
) -> tuple[bytes, int]:
    return upload_files.load_export(path, expected_list_key=expected_list_key)


def _build_lastfm_parts(path: Path, content: bytes) -> tuple[GeneratedPart, ...]:
    return upload_files.build_parts(path, content, LASTFM_PART_SIZE)


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
    from spotify_manager.interfaces.operations.upload_library_files import (
        prepare_library_files_upload as operation,
    )

    return operation(
        include_your_library=include_your_library,
        include_lastfm=include_lastfm,
        repo_id=repo_id,
        revision=revision,
        files_dir=files_dir,
    )


def materialize_lastfm_parts(plan: LibraryFilesUploadPlan) -> None:
    """Atomically replace local fallback parts and remove obsolete fallbacks.

    Args:
        plan: Original prepared source and generated-part manifest.
    """
    upload_files.materialize(plan)


def upload_library_files(
    plan: LibraryFilesUploadPlan,
    *,
    api: HfApi | None = None,
) -> LibraryFilesUploadResult:
    """Upload the plan to the configured HF Space in one commit.

    Args:
        plan: Original prepared source and generated-part manifest.
        api: Original optional caller-owned Hugging Face client.

    Returns:
        Original upload library files result.
    """
    from spotify_manager.interfaces.operations.upload_library_files import (
        upload_library_files as operation,
    )

    return operation(plan, api=api)


def _part_suffix(index: int) -> str:
    return part_suffix(index)
