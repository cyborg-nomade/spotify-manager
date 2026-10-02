"""Original export validation, compression and local fallback publication."""

import base64
import gzip
import json
from pathlib import Path

from spotify_manager.application.upload_values import LASTFM_BINARY_PART_PREFIX
from spotify_manager.application.upload_values import LASTFM_COMPRESSED_FILENAME
from spotify_manager.application.upload_values import LASTFM_PART_PREFIX
from spotify_manager.application.upload_values import LASTFM_PART_SIZE
from spotify_manager.application.upload_values import REMOTE_FILES_DIR
from spotify_manager.application.upload_values import GeneratedPart
from spotify_manager.application.upload_values import LibraryFilesUploadPlan
from spotify_manager.domain.upload_manifest import LibraryFilesUploadError
from spotify_manager.domain.upload_manifest import part_suffix


def load_export(
    path: Path,
    *,
    expected_list_key: str,
) -> tuple[bytes, int]:
    """Read original export bytes and validate only its required array.

    Args:
        path: Original selected source.
        expected_list_key: Original required top-level array.

    Returns:
        Unchanged bytes and raw row count.

    Raises:
        LibraryFilesUploadError: Original read or shallow validation fails.
    """
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


def build_parts(
    path: Path, content: bytes, part_size: int = LASTFM_PART_SIZE
) -> tuple[GeneratedPart, ...]:
    """Build original deterministic gzip/base64 parts without writing files.

    Args:
        path: Original source location.
        content: Original source bytes.

    Returns:
        Ordered inline fallback parts.
    """
    compressed = gzip.compress(content, compresslevel=9, mtime=0)
    encoded = base64.b64encode(compressed)
    parts: list[GeneratedPart] = []
    for index, offset in enumerate(range(0, len(encoded), part_size)):
        filename = f"{LASTFM_PART_PREFIX}{part_suffix(index)}"
        parts.append(
            GeneratedPart(
                local_path=path.parent / filename,
                path_in_repo=f"{REMOTE_FILES_DIR}/{filename}",
                content=encoded[offset : offset + part_size],
            )
        )
    return tuple(parts)


def materialize(plan: LibraryFilesUploadPlan) -> None:
    """Publish original local parts and retain original partial-failure cleanup.

    Args:
        plan: Original prepared manifest.

    Raises:
        LibraryFilesUploadError: Original publication fails.
        OSError: Original final cleanup fails and overrides publication errors.
    """
    if not plan.lastfm_parts:
        return
    temporary: list[Path] = []
    try:
        _write_temporary(plan.lastfm_parts, temporary)
        _replace_parts(plan.lastfm_parts, temporary)
        _purge_obsolete(plan.lastfm_parts)
    except OSError as error:
        raise LibraryFilesUploadError(
            f"Could not update local Last.fm fallback parts: {error}"
        ) from error
    finally:
        for path in temporary:
            path.unlink(missing_ok=True)


def _write_temporary(parts: tuple[GeneratedPart, ...], temporary: list[Path]) -> None:
    for part in parts:
        path = part.local_path.with_name(f".{part.local_path.name}.tmp")
        path.write_bytes(part.content)
        temporary.append(path)


def _replace_parts(parts: tuple[GeneratedPart, ...], temporary: list[Path]) -> None:
    for part, path in zip(parts, temporary, strict=True):
        path.replace(part.local_path)


def _purge_obsolete(parts: tuple[GeneratedPart, ...]) -> None:
    desired = {part.local_path for part in parts}
    directory = parts[0].local_path.parent
    for path in directory.glob(f"{LASTFM_PART_PREFIX}*"):
        if path not in desired:
            path.unlink()
    (directory / LASTFM_COMPRESSED_FILENAME).unlink(missing_ok=True)
    for path in directory.glob(f"{LASTFM_BINARY_PART_PREFIX}*"):
        path.unlink()
