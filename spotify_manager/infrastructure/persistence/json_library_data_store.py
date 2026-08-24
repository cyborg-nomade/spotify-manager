"""Local filesystem adapter for durable canonical library files."""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from pathlib import Path
from threading import Lock
from typing import Any

from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.core.library_data.models import LibraryDataDocumentError
from spotify_manager.core.library_data.models import LibraryDataIntegrityError
from spotify_manager.core.library_data.models import LibraryDataSnapshot
from spotify_manager.core.library_data.models import manifest_bytes
from spotify_manager.core.library_data.models import new_manifest
from spotify_manager.core.library_data.models import validate_manifest


MISSING_REVISION = "missing"


class JsonLibraryDataStore:
    """Persist a manifest and compressed blobs beneath one local directory."""

    def __init__(self, root: Path, *, manifest_filename: str = "manifest.json") -> None:
        """Use ``root`` as an isolated durable-data store."""
        self.root = root
        self.manifest_path = root / manifest_filename
        self._lock = Lock()

    @staticmethod
    def _revision(contents: bytes) -> str:
        return hashlib.sha256(contents).hexdigest()

    def _read_unlocked(self) -> LibraryDataSnapshot:
        if not self.manifest_path.exists():
            return LibraryDataSnapshot(new_manifest(), MISSING_REVISION)
        try:
            contents = self.manifest_path.read_bytes()
            raw: Any = json.loads(contents)
        except (OSError, json.JSONDecodeError) as exc:
            raise LibraryDataDocumentError(
                f"Could not read library-data manifest from {self.manifest_path}."
            ) from exc
        return LibraryDataSnapshot(validate_manifest(raw), self._revision(contents))

    def read(self) -> LibraryDataSnapshot:
        """Read one validated local manifest."""
        with self._lock:
            return self._read_unlocked()

    def restore(
        self,
        name: ArtifactName,
        metadata: ArtifactMetadata,
        *,
        revision: str,
        destination: Path,
    ) -> None:
        """Restore one compressed local blob."""
        del name
        with self._lock:
            current = self._read_unlocked()
            if current.revision != revision:
                raise LibraryDataConflictError(
                    "Library data changed before the local restore completed."
                )
            blob = self.root / metadata.blob_path
            try:
                with gzip.open(blob, "rb") as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
            except FileNotFoundError as exc:
                raise LibraryDataIntegrityError(
                    f"Durable blob for {metadata.filename} is missing."
                ) from exc
            except (OSError, EOFError) as exc:
                raise LibraryDataIntegrityError(
                    f"Could not restore durable blob for {metadata.filename}."
                ) from exc

    def write(
        self,
        name: ArtifactName,
        payload: bytes,
        manifest: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> LibraryDataSnapshot:
        """Write a compressed blob, then atomically replace its manifest."""
        del message
        validated = validate_manifest(manifest)
        metadata = validated["artifacts"][name]
        contents = manifest_bytes(validated)
        with self._lock:
            current = self._read_unlocked()
            if current.revision != expected_revision:
                raise LibraryDataConflictError(
                    "Library data changed before the local write completed."
                )
            blob = self.root / metadata["blob_path"]
            blob.parent.mkdir(parents=True, exist_ok=True)
            blob_temporary = blob.with_suffix(f"{blob.suffix}.tmp")
            manifest_temporary = self.manifest_path.with_suffix(
                f"{self.manifest_path.suffix}.tmp"
            )
            try:
                blob_temporary.write_bytes(
                    gzip.compress(payload, compresslevel=9, mtime=0)
                )
                blob_temporary.replace(blob)
                manifest_temporary.write_bytes(contents)
                manifest_temporary.replace(self.manifest_path)
            except OSError as exc:
                raise LibraryDataDocumentError(
                    f"Could not write library data beneath {self.root}."
                ) from exc
            finally:
                blob_temporary.unlink(missing_ok=True)
                manifest_temporary.unlink(missing_ok=True)
        return LibraryDataSnapshot(validated, self._revision(contents))
