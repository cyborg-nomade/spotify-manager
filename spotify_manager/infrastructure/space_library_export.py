"""Resolve a packaged Git LFS export without changing its source identity."""

import hashlib
import json
import re
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from httpx import HTTPError
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import HfHubHTTPError
from huggingface_hub.errors import LocalEntryNotFoundError
from pydantic import ValidationError

from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.models.your_library import YourLibraryFile


_POINTER = re.compile(
    r"version https://git-lfs.github.com/spec/v1\n"
    r"oid sha256:([a-f0-9]{64})\nsize ([0-9]+)\n?"
)


@dataclass(frozen=True)
class ExportPointer:
    """Identify the exact bytes referenced by a packaged source export.

    Args:
        sha256: Expected Git LFS content digest.
        size: Expected uncompressed source size in bytes.
    """

    sha256: str
    size: int


def export_pointer(failure: LibrarySyncError) -> ExportPointer | None:
    """Recognize a complete Git LFS pointer from the failed JSON observation.

    Args:
        failure: Source read failure retaining its original JSON decoder cause.

    Returns:
        Expected source identity, or None for ordinary corruption or read errors.
    """
    cause = failure.__cause__
    if not isinstance(cause, json.JSONDecodeError):
        return None
    match = _POINTER.fullmatch(cause.doc.replace("\r\n", "\n"))
    if match is None:
        return None
    return ExportPointer(match[1], int(match[2]))


@dataclass(frozen=True)
class SpaceLibraryExport:
    """Read the exact source export referenced by the running Space's LFS pointer.

    Args:
        path: Only packaged source path eligible for recovery.
        repo_id: Owning Space repository, supplied by bootstrap.
        token: Existing Hub credential; omitted from object representations.
    """

    path: Path
    repo_id: str
    token: str | None = field(default=None, repr=False)

    def recover(self, path: Path, failure: LibrarySyncError) -> YourLibraryFile:
        """Recover only an exact pointer; preserve ordinary invalid-export failures.

        Args:
            path: Source path that could not be parsed.
            failure: Original source failure and decoder cause.

        Returns:
            Validated export with the packaged content identity.

        Raises:
            LibrarySyncError: Recovery is inapplicable, unavailable, or invalid.
        """
        pointer = export_pointer(failure)
        if pointer is None or path.resolve() != self.path.resolve():
            raise failure
        content = self._download()
        _verify_content(content, pointer)
        try:
            return YourLibraryFile.model_validate_json(content)
        except ValidationError as exc:
            raise LibrarySyncError(
                "Downloaded Your Library export is invalid."
            ) from exc

    def _download(self) -> bytes:
        try:
            cached = hf_hub_download(
                repo_id=self.repo_id,
                filename="spotify_manager/files/YourLibrary.json",
                repo_type="space",
                token=self.token,
            )
            return Path(cached).read_bytes()
        except (HfHubHTTPError, LocalEntryNotFoundError, HTTPError, OSError) as exc:
            raise LibrarySyncError(
                "Could not resolve the packaged Your Library Git LFS export "
                "from the Space repository; the artist mirror was not replaced."
            ) from exc


def _verify_content(content: bytes, pointer: ExportPointer) -> None:
    if len(content) != pointer.size:
        raise LibrarySyncError("Your Library Git LFS export size does not match.")
    if hashlib.sha256(content).hexdigest() != pointer.sha256:
        raise LibrarySyncError("Your Library Git LFS export digest does not match.")
