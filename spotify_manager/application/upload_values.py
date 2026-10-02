"""Original upload metadata, deterministic fallback names and results."""

from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from spotify_manager.domain.upload_manifest import (
    LibraryFilesUploadError as LibraryFilesUploadError,
)


DEFAULT_REPO_ID = "cyborg-nomade/spotify-manager"
DEFAULT_REVISION = "main"
REMOTE_FILES_DIR = "spotify_manager/files"
YOUR_LIBRARY_FILENAME = "YourLibrary.json"
LASTFM_FILENAME = "lastfmstats-man-et-arms.json"
LASTFM_COMPRESSED_FILENAME = f"{LASTFM_FILENAME}.gz"
LASTFM_BINARY_PART_PREFIX = f"{LASTFM_COMPRESSED_FILENAME}.part-"
LASTFM_PART_PREFIX = f"{LASTFM_FILENAME}.gz.b64.part-"
LASTFM_PART_SIZE = 2_000_000


@dataclass(frozen=True)
class GeneratedPart:
    """One inline, compressed Last.fm fallback part.

    Args:
        local_path: Original managed local file path.
        path_in_repo: Original remote manifest path.
        content: Original inline deterministic fallback bytes.
    """

    local_path: Path
    path_in_repo: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class UploadResource:
    """A source export included in an upload.

    Args:
        name: Original source filename.
        local_path: Original managed local file path.
        path_in_repo: Original remote manifest path.
        item_count: Original raw export row count.
        size_bytes: Original uncompressed source size.
    """

    name: str
    local_path: Path
    path_in_repo: str
    item_count: int
    size_bytes: int


@dataclass(frozen=True)
class LibraryFilesUploadPlan:
    """Validated files and generated content ready for one HF commit.

    Args:
        repo_id: Original target Space identity.
        revision: Original target revision.
        resources: Original selected source order.
        lastfm_parts: Original generated fallback part order.
    """

    repo_id: str
    revision: str
    resources: tuple[UploadResource, ...]
    lastfm_parts: tuple[GeneratedPart, ...] = ()

    @property
    def upload_file_count(self) -> int:
        """Return the number of files that will be added or replaced."""
        return len(self.resources) + len(self.lastfm_parts)

    @property
    def upload_size_bytes(self) -> int:
        """Return the total uncompressed upload payload size."""
        total = 0
        for resource in self.resources:
            total += resource.size_bytes
        for part in self.lastfm_parts:
            total += len(part.content)
        return total


@dataclass(frozen=True)
class LibraryFilesUploadResult:
    """Summary of a completed HF commit.

    Args:
        commit_url: Original accepted commit URL.
        uploaded_files: Original source and part count.
        deleted_stale_parts: Original obsolete remote fallback count.
        upload_size_bytes: Original source and generated-part byte total.
    """

    commit_url: str
    uploaded_files: int
    deleted_stale_parts: int
    upload_size_bytes: int
