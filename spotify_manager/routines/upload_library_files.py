"""Upload refreshed library exports to the Hugging Face Space."""

import base64
import gzip
import json
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete
from huggingface_hub import HfApi


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_REPO_ID = "cyborg-nomade/spotify-manager"
DEFAULT_REVISION = "main"
REMOTE_FILES_DIR = "spotify_manager/files"
YOUR_LIBRARY_FILENAME = "YourLibrary.json"
LASTFM_FILENAME = "lastfmstats-man-et-arms.json"
LASTFM_COMPRESSED_FILENAME = f"{LASTFM_FILENAME}.gz"
LASTFM_BINARY_PART_PREFIX = f"{LASTFM_COMPRESSED_FILENAME}.part-"
LASTFM_PART_PREFIX = f"{LASTFM_FILENAME}.gz.b64.part-"
LASTFM_PART_SIZE = 2_000_000


class LibraryFilesUploadError(RuntimeError):
    """Raised when local exports cannot be prepared or uploaded."""


@dataclass(frozen=True)
class GeneratedPart:
    """One inline, compressed Last.fm fallback part."""

    local_path: Path
    path_in_repo: str
    content: bytes = field(repr=False)


@dataclass(frozen=True)
class UploadResource:
    """A source export included in an upload."""

    name: str
    local_path: Path
    path_in_repo: str
    item_count: int
    size_bytes: int


@dataclass(frozen=True)
class LibraryFilesUploadPlan:
    """Validated files and generated content ready for one HF commit."""

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
        return sum(resource.size_bytes for resource in self.resources) + sum(
            len(part.content) for part in self.lastfm_parts
        )


@dataclass(frozen=True)
class LibraryFilesUploadResult:
    """Summary of a completed HF commit."""

    commit_url: str
    uploaded_files: int
    deleted_stale_parts: int
    upload_size_bytes: int


def _remote_path(filename: str) -> str:
    return f"{REMOTE_FILES_DIR}/{filename}"


def _load_and_validate_export(
    path: Path,
    *,
    expected_list_key: str,
) -> tuple[bytes, int]:
    if not path.is_file():
        raise LibraryFilesUploadError(f"Export file does not exist: {path}")

    try:
        content = path.read_bytes()
    except OSError as exc:
        raise LibraryFilesUploadError(
            f"Could not read export file {path}: {exc}"
        ) from exc

    try:
        payload = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryFilesUploadError(f"Export is not valid JSON: {path}") from exc

    items = payload.get(expected_list_key) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise LibraryFilesUploadError(
            f"Export must contain a '{expected_list_key}' list: {path}"
        )
    return content, len(items)


def _part_suffix(index: int) -> str:
    if index < 0 or index >= 26 * 26:
        raise LibraryFilesUploadError(
            "Last.fm export requires too many fallback parts."
        )
    return f"{chr(ord('a') + index // 26)}{chr(ord('a') + index % 26)}"


def _build_lastfm_parts(path: Path, content: bytes) -> tuple[GeneratedPart, ...]:
    compressed = gzip.compress(content, compresslevel=9, mtime=0)
    encoded = base64.b64encode(compressed)
    parts: list[GeneratedPart] = []
    for index, offset in enumerate(range(0, len(encoded), LASTFM_PART_SIZE)):
        filename = f"{LASTFM_PART_PREFIX}{_part_suffix(index)}"
        parts.append(
            GeneratedPart(
                local_path=path.parent / filename,
                path_in_repo=_remote_path(filename),
                content=encoded[offset : offset + LASTFM_PART_SIZE],
            )
        )
    return tuple(parts)


def prepare_library_files_upload(
    *,
    include_your_library: bool = True,
    include_lastfm: bool = True,
    repo_id: str = DEFAULT_REPO_ID,
    revision: str = DEFAULT_REVISION,
    files_dir: Path = FILES_DIR,
) -> LibraryFilesUploadPlan:
    """Validate selected exports and prepare deterministic Last.fm parts."""
    if not include_your_library and not include_lastfm:
        raise LibraryFilesUploadError("Select at least one export to upload.")

    resources: list[UploadResource] = []
    lastfm_parts: tuple[GeneratedPart, ...] = ()

    if include_your_library:
        path = files_dir / YOUR_LIBRARY_FILENAME
        content, item_count = _load_and_validate_export(
            path,
            expected_list_key="tracks",
        )
        resources.append(
            UploadResource(
                name=YOUR_LIBRARY_FILENAME,
                local_path=path,
                path_in_repo=_remote_path(YOUR_LIBRARY_FILENAME),
                item_count=item_count,
                size_bytes=len(content),
            )
        )

    if include_lastfm:
        path = files_dir / LASTFM_FILENAME
        content, item_count = _load_and_validate_export(
            path,
            expected_list_key="scrobbles",
        )
        resources.append(
            UploadResource(
                name=LASTFM_FILENAME,
                local_path=path,
                path_in_repo=_remote_path(LASTFM_FILENAME),
                item_count=item_count,
                size_bytes=len(content),
            )
        )
        lastfm_parts = _build_lastfm_parts(path, content)

    return LibraryFilesUploadPlan(
        repo_id=repo_id,
        revision=revision,
        resources=tuple(resources),
        lastfm_parts=lastfm_parts,
    )


def materialize_lastfm_parts(plan: LibraryFilesUploadPlan) -> None:
    """Atomically replace local fallback parts and remove obsolete fallbacks."""
    if not plan.lastfm_parts:
        return

    desired_paths = {part.local_path for part in plan.lastfm_parts}
    files_dir = plan.lastfm_parts[0].local_path.parent
    temporary_paths: list[Path] = []
    try:
        for part in plan.lastfm_parts:
            temporary_path = part.local_path.with_name(f".{part.local_path.name}.tmp")
            temporary_path.write_bytes(part.content)
            temporary_paths.append(temporary_path)
        for part, temporary_path in zip(
            plan.lastfm_parts, temporary_paths, strict=True
        ):
            temporary_path.replace(part.local_path)
        for existing_path in files_dir.glob(f"{LASTFM_PART_PREFIX}*"):
            if existing_path not in desired_paths:
                existing_path.unlink()
        (files_dir / LASTFM_COMPRESSED_FILENAME).unlink(missing_ok=True)
        for existing_path in files_dir.glob(f"{LASTFM_BINARY_PART_PREFIX}*"):
            existing_path.unlink()
    except OSError as exc:
        raise LibraryFilesUploadError(
            f"Could not update local Last.fm fallback parts: {exc}"
        ) from exc
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)


def upload_library_files(
    plan: LibraryFilesUploadPlan,
    *,
    api: HfApi | None = None,
) -> LibraryFilesUploadResult:
    """Upload the plan to the configured HF Space in one commit."""
    client = api or HfApi()
    try:
        remote_files = set(
            client.list_repo_files(
                repo_id=plan.repo_id,
                repo_type="space",
                revision=plan.revision,
            )
        )
    except Exception as exc:
        raise LibraryFilesUploadError(
            f"Could not read files from HF Space '{plan.repo_id}': {exc}. "
            "Confirm `hf auth login` and your access to the Space."
        ) from exc

    desired_part_paths = {part.path_in_repo for part in plan.lastfm_parts}
    stale_part_paths: set[str] = set()
    if plan.lastfm_parts:
        remote_prefix = _remote_path(LASTFM_PART_PREFIX)
        remote_binary_prefix = _remote_path(LASTFM_BINARY_PART_PREFIX)
        remote_compressed_path = _remote_path(LASTFM_COMPRESSED_FILENAME)
        stale_part_paths = {
            path
            for path in remote_files
            if (
                path == remote_compressed_path
                or path.startswith(remote_binary_prefix)
                or (path.startswith(remote_prefix) and path not in desired_part_paths)
            )
        }

    materialize_lastfm_parts(plan)
    operations: list[CommitOperationAdd | CommitOperationDelete] = [
        CommitOperationAdd(
            path_in_repo=resource.path_in_repo,
            path_or_fileobj=resource.local_path,
        )
        for resource in plan.resources
    ]
    operations.extend(
        CommitOperationAdd(
            path_in_repo=part.path_in_repo,
            path_or_fileobj=part.content,
        )
        for part in plan.lastfm_parts
    )
    operations.extend(
        CommitOperationDelete(path_in_repo=path) for path in sorted(stale_part_paths)
    )

    selected_names = ", ".join(resource.name for resource in plan.resources)
    try:
        commit = client.create_commit(
            repo_id=plan.repo_id,
            repo_type="space",
            revision=plan.revision,
            operations=operations,
            commit_message=f"Update library exports: {selected_names}",
        )
    except Exception as exc:
        raise LibraryFilesUploadError(
            f"HF upload to '{plan.repo_id}' failed: {exc}. "
            "The local fallback parts are current, so the command can be retried."
        ) from exc

    commit_url = getattr(commit, "commit_url", None)
    if not isinstance(commit_url, str):
        raise LibraryFilesUploadError(
            "HF accepted the commit but did not return a commit URL."
        )
    return LibraryFilesUploadResult(
        commit_url=commit_url,
        uploaded_files=plan.upload_file_count,
        deleted_stale_parts=len(stale_part_paths),
        upload_size_bytes=plan.upload_size_bytes,
    )
