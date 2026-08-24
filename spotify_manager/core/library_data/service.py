"""Central service for shared canonical library files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import RLock

from spotify_manager.core.library_data.models import ALL_ARTIFACTS
from spotify_manager.core.library_data.models import ARTIFACT_FILENAMES
from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.core.library_data.models import LibraryDataIntegrityError
from spotify_manager.core.library_data.models import LibraryDataSnapshot
from spotify_manager.core.library_data.models import artifact_metadata
from spotify_manager.core.library_data.models import payload_sha256
from spotify_manager.core.library_data.models import utc_now
from spotify_manager.core.library_data.models import validate_artifact_payload
from spotify_manager.core.library_data.models import validate_manifest
from spotify_manager.core.library_data.models import with_artifact
from spotify_manager.core.library_data.store import LibraryDataStore


MAX_WRITE_ATTEMPTS = 5


@dataclass(frozen=True)
class ArtifactStatus:
    """Remote metadata and local synchronization status for one artifact."""

    name: ArtifactName
    filename: str
    exists: bool
    updated_at: str | None
    size_bytes: int | None
    sha256: str | None
    source: str | None
    local_current: bool


class LibraryDataService:
    """Hydrate and publish all managed files through one interface."""

    def __init__(
        self,
        store: LibraryDataStore,
        paths: dict[ArtifactName, Path],
    ) -> None:
        """Bind durable artifact names to their working-tree paths."""
        missing = set(ALL_ARTIFACTS) - set(paths)
        if missing:
            raise ValueError(f"Missing library-data paths: {sorted(missing)}")
        self._store = store
        self.paths = dict(paths)
        self._baselines: dict[ArtifactName, str | None] = {}
        self._lock = RLock()

    def snapshot(self) -> LibraryDataSnapshot:
        """Return one detached, validated manifest snapshot."""
        snapshot = self._store.read()
        return LibraryDataSnapshot(
            document=validate_manifest(snapshot.document),
            revision=snapshot.revision,
        )

    @staticmethod
    def _local_digest(path: Path) -> str | None:
        try:
            return payload_sha256(path.read_bytes())
        except FileNotFoundError:
            return None

    @staticmethod
    def _apply_timestamp(path: Path, updated_at: str) -> None:
        try:
            timestamp = datetime.fromisoformat(updated_at).timestamp()
            os.utime(path, (timestamp, timestamp))
        except OSError, ValueError:
            return

    def hydrate(
        self,
        name: ArtifactName,
        *,
        snapshot: LibraryDataSnapshot | None = None,
    ) -> ArtifactStatus:
        """Make one working JSON file match the durable manifest."""
        with self._lock:
            current = snapshot or self.snapshot()
            metadata = artifact_metadata(current.document, name)
            path = self.paths[name]
            if metadata is None:
                self._baselines[name] = None
                return ArtifactStatus(
                    name=name,
                    filename=ARTIFACT_FILENAMES[name],
                    exists=False,
                    updated_at=None,
                    size_bytes=None,
                    sha256=None,
                    source=None,
                    local_current=False,
                )
            local_digest = self._local_digest(path)
            if local_digest != metadata.sha256:
                path.parent.mkdir(parents=True, exist_ok=True)
                temporary = path.with_suffix(f"{path.suffix}.hydrate.tmp")
                try:
                    self._store.restore(
                        name,
                        metadata,
                        revision=current.revision,
                        destination=temporary,
                    )
                    payload = temporary.read_bytes()
                    if len(payload) != metadata.size_bytes:
                        raise LibraryDataIntegrityError(
                            f"Restored {metadata.filename} has the wrong size."
                        )
                    if payload_sha256(payload) != metadata.sha256:
                        raise LibraryDataIntegrityError(
                            f"Restored {metadata.filename} failed its checksum."
                        )
                    validate_artifact_payload(name, payload)
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
            self._apply_timestamp(path, metadata.updated_at)
            self._baselines[name] = metadata.sha256
            return ArtifactStatus(
                name=name,
                filename=metadata.filename,
                exists=True,
                updated_at=metadata.updated_at,
                size_bytes=metadata.size_bytes,
                sha256=metadata.sha256,
                source=metadata.source,
                local_current=True,
            )

    def hydrate_all(self) -> tuple[ArtifactStatus, ...]:
        """Hydrate every managed path from one immutable manifest revision."""
        snapshot = self.snapshot()
        return tuple(self.hydrate(name, snapshot=snapshot) for name in ALL_ARTIFACTS)

    def publish(
        self,
        name: ArtifactName,
        *,
        source: str,
        message: str | None = None,
    ) -> LibraryDataSnapshot:
        """Publish one validated working file without clobbering a newer peer."""
        with self._lock:
            path = self.paths[name]
            try:
                payload = path.read_bytes()
            except OSError as exc:
                raise LibraryDataIntegrityError(
                    f"Could not read managed artifact {path}."
                ) from exc
            validate_artifact_payload(name, payload)
            digest = payload_sha256(payload)
            baseline_known = name in self._baselines
            baseline = self._baselines.get(name)
            for attempt in range(MAX_WRITE_ATTEMPTS):
                current = self.snapshot()
                current_metadata = artifact_metadata(current.document, name)
                current_digest = (
                    current_metadata.sha256 if current_metadata is not None else None
                )
                if baseline_known and current_digest not in {baseline, digest}:
                    raise LibraryDataConflictError(
                        f"{ARTIFACT_FILENAMES[name]} changed in another process. "
                        "Hydrate it before publishing again."
                    )
                timestamp = utc_now()
                metadata = ArtifactMetadata(
                    filename=ARTIFACT_FILENAMES[name],
                    blob_path=f"artifacts/{ARTIFACT_FILENAMES[name]}.gz",
                    sha256=digest,
                    size_bytes=len(payload),
                    updated_at=timestamp,
                    source=source,
                )
                document = with_artifact(current.document, name, metadata)
                try:
                    saved = self._store.write(
                        name,
                        payload,
                        document,
                        expected_revision=current.revision,
                        message=message or f"Update {metadata.filename}",
                    )
                except LibraryDataConflictError:
                    if attempt + 1 == MAX_WRITE_ATTEMPTS:
                        raise
                    continue
                self._baselines[name] = digest
                self._apply_timestamp(path, timestamp)
                return saved
            raise AssertionError("library-data write retry loop did not return")

    def statuses(self) -> tuple[ArtifactStatus, ...]:
        """Report durable metadata and whether each local mirror is current."""
        snapshot = self.snapshot()
        statuses: list[ArtifactStatus] = []
        for name in ALL_ARTIFACTS:
            metadata = artifact_metadata(snapshot.document, name)
            local_digest = self._local_digest(self.paths[name])
            statuses.append(
                ArtifactStatus(
                    name=name,
                    filename=ARTIFACT_FILENAMES[name],
                    exists=metadata is not None,
                    updated_at=metadata.updated_at if metadata else None,
                    size_bytes=metadata.size_bytes if metadata else None,
                    sha256=metadata.sha256 if metadata else None,
                    source=metadata.source if metadata else None,
                    local_current=(
                        metadata is not None and local_digest == metadata.sha256
                    ),
                )
            )
        return tuple(statuses)
