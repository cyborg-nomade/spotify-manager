"""Manifest models for durable canonical library files."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal
from typing import cast


LIBRARY_DATA_SCHEMA_VERSION = 1
ArtifactName = Literal["albums", "tracks", "artists", "scrobbles"]
ALL_ARTIFACTS: tuple[ArtifactName, ...] = (
    "albums",
    "tracks",
    "artists",
    "scrobbles",
)
ARTIFACT_FILENAMES: dict[ArtifactName, str] = {
    "albums": "albums_total_new.json",
    "tracks": "liked_tracks_total.json",
    "artists": "artists_total.json",
    "scrobbles": "lastfmstats-man-et-arms.json",
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class LibraryDataError(RuntimeError):
    """Base error for durable library-data operations."""


class LibraryDataDocumentError(LibraryDataError):
    """Raised when a manifest or managed JSON file is malformed."""


class LibraryDataConflictError(LibraryDataError):
    """Raised when another process changed a managed artifact."""


class LibraryDataConfigurationError(LibraryDataError):
    """Raised when the configured durable store cannot be reached."""


class LibraryDataIntegrityError(LibraryDataError):
    """Raised when downloaded bytes do not match their manifest."""


@dataclass(frozen=True)
class ArtifactMetadata:
    """Version and provenance of one canonical JSON artifact."""

    filename: str
    blob_path: str
    sha256: str
    size_bytes: int
    updated_at: str
    source: str

    def as_dict(self) -> dict[str, object]:
        """Return JSON-compatible manifest data."""
        return {
            "filename": self.filename,
            "blob_path": self.blob_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "updated_at": self.updated_at,
            "source": self.source,
        }


@dataclass(frozen=True)
class LibraryDataSnapshot:
    """One validated manifest at an immutable store revision."""

    document: dict[str, Any]
    revision: str


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


def new_manifest() -> dict[str, Any]:
    """Return an empty manifest using the current schema."""
    timestamp = utc_now()
    return {
        "schema_version": LIBRARY_DATA_SCHEMA_VERSION,
        "created_at": timestamp,
        "updated_at": timestamp,
        "artifacts": {},
    }


def validate_artifact_name(value: object) -> ArtifactName:
    """Return a supported artifact name or reject it."""
    if value not in ALL_ARTIFACTS:
        raise LibraryDataDocumentError(f"Unknown library-data artifact: {value!r}.")
    return cast(ArtifactName, value)


def _metadata(name: ArtifactName, raw: object) -> ArtifactMetadata:
    if not isinstance(raw, dict):
        raise LibraryDataDocumentError(f"Artifact {name!r} metadata must be an object.")
    filename = raw.get("filename")
    blob_path = raw.get("blob_path")
    sha256 = raw.get("sha256")
    size_bytes = raw.get("size_bytes")
    updated_at = raw.get("updated_at")
    source = raw.get("source")
    if filename != ARTIFACT_FILENAMES[name]:
        raise LibraryDataDocumentError(
            f"Artifact {name!r} must use filename {ARTIFACT_FILENAMES[name]!r}."
        )
    if not isinstance(blob_path, str) or not blob_path.startswith("artifacts/"):
        raise LibraryDataDocumentError(f"Artifact {name!r} has an invalid blob path.")
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        raise LibraryDataDocumentError(f"Artifact {name!r} has an invalid checksum.")
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes < 0
    ):
        raise LibraryDataDocumentError(f"Artifact {name!r} has an invalid size.")
    if not isinstance(updated_at, str) or not updated_at:
        raise LibraryDataDocumentError(f"Artifact {name!r} has no update timestamp.")
    if not isinstance(source, str) or not source:
        raise LibraryDataDocumentError(f"Artifact {name!r} has no source label.")
    return ArtifactMetadata(
        filename=filename,
        blob_path=blob_path,
        sha256=sha256,
        size_bytes=size_bytes,
        updated_at=updated_at,
        source=source,
    )


def validate_manifest(raw: object) -> dict[str, Any]:
    """Validate and detach a durable library-data manifest."""
    if not isinstance(raw, dict):
        raise LibraryDataDocumentError("Library-data manifest must be an object.")
    if raw.get("schema_version") != LIBRARY_DATA_SCHEMA_VERSION:
        raise LibraryDataDocumentError(
            f"Library-data schema_version must be {LIBRARY_DATA_SCHEMA_VERSION}."
        )
    for field in ("created_at", "updated_at"):
        if not isinstance(raw.get(field), str):
            raise LibraryDataDocumentError(f"Library-data {field} must be a string.")
    artifacts = raw.get("artifacts")
    if not isinstance(artifacts, dict):
        raise LibraryDataDocumentError("Library-data artifacts must be an object.")
    for raw_name, raw_metadata in artifacts.items():
        name = validate_artifact_name(raw_name)
        _metadata(name, raw_metadata)
    try:
        json.dumps(raw, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LibraryDataDocumentError(
            f"Library-data manifest is not valid JSON data: {exc}"
        ) from exc
    return copy.deepcopy(raw)


def artifact_metadata(
    manifest: dict[str, Any],
    name: ArtifactName,
) -> ArtifactMetadata | None:
    """Return validated metadata for one artifact when it exists."""
    raw = validate_manifest(manifest)["artifacts"].get(name)
    return None if raw is None else _metadata(name, raw)


def with_artifact(
    manifest: dict[str, Any],
    name: ArtifactName,
    metadata: ArtifactMetadata,
) -> dict[str, Any]:
    """Return a manifest copy containing one updated artifact."""
    updated = validate_manifest(manifest)
    updated["updated_at"] = metadata.updated_at
    updated["artifacts"][name] = metadata.as_dict()
    return validate_manifest(updated)


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    """Serialize a validated manifest deterministically."""
    return (
        json.dumps(
            validate_manifest(manifest),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode()


def payload_sha256(payload: bytes) -> str:
    """Return the content identity stored in the manifest."""
    return hashlib.sha256(payload).hexdigest()


def validate_artifact_payload(name: ArtifactName, payload: bytes) -> None:
    """Reject invalid JSON or the wrong top-level shape before publication."""
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LibraryDataDocumentError(
            f"{ARTIFACT_FILENAMES[name]} is not valid JSON."
        ) from exc
    if name == "scrobbles":
        valid = isinstance(raw, dict) and isinstance(raw.get("scrobbles"), list)
    else:
        valid = isinstance(raw, list)
    if not valid:
        expected = (
            "an object with a scrobbles list" if name == "scrobbles" else "a list"
        )
        raise LibraryDataDocumentError(
            f"{ARTIFACT_FILENAMES[name]} must contain {expected}."
        )
