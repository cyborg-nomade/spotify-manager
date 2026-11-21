"""Read complete Spotify collections from one verified publication revision."""

import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from typing import cast

from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.core.library_data.models import LibraryDataError
from spotify_manager.core.library_data.models import LibraryDataSnapshot
from spotify_manager.core.library_data.models import artifact_metadata
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import LibraryEntry
from spotify_manager.domain.listening_library_values import MirrorSource
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import EntityKind


COLLECTIONS: tuple[tuple[ArtifactName, EntityKind], ...] = (
    ("artists", "artist"),
    ("albums", "album"),
    ("tracks", "track"),
)


def _text(row: dict[str, object], name: str) -> str:
    value = row.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A collection row has an invalid required name.")
    return value.strip()


def _entry(raw: object, kind: EntityKind) -> LibraryEntry:
    if not isinstance(raw, dict):
        raise ValueError("A collection row must be an object.")
    row = cast(dict[str, object], raw)
    uri = _text(row, "uri")
    if re.fullmatch(r"spotify:" + kind + r":[A-Za-z0-9]{22}", uri) is None:
        raise ValueError("A collection row has an invalid Spotify identity.")
    name = _text(row, "name" if kind == "artist" else kind)
    artist = "" if kind == "artist" else _text(row, "artist")
    parts = (name,) if kind == "artist" else (artist, name)
    return LibraryEntry(kind, listening_identity(parts), name, artist, uri)


def _decode(path: Path, kind: EntityKind) -> tuple[LibraryEntry, ...]:
    raw: object = json.loads(path.read_bytes())
    if not isinstance(raw, list):
        raise ValueError("A collection publication must be a list.")
    entries = {}
    for row in raw:
        entry = _entry(row, kind)
        entries[(entry.key, entry.uri)] = entry
    return tuple(entries.values())


def _source(
    kind: EntityKind,
    metadata: ArtifactMetadata | None,
    state: str,
    count: int = 0,
) -> MirrorSource:
    if metadata is None:
        return MirrorSource(kind, "missing", None, None, None, 0, "Not published.")
    status: Literal["ready", "error"] = "ready" if state == "ready" else "error"
    message = (
        "Complete publication verified."
        if status == "ready"
        else "Publication unavailable or invalid; membership is unknown."
    )
    return MirrorSource(
        kind,
        status,
        metadata.updated_at,
        metadata.sha256,
        metadata.source,
        count,
        message,
    )


class LibraryPublications:
    """Acquire current collections without hydrating or publishing managed files.

    Args:
        service: Existing revision-aware durable artifact reader.
    """

    def __init__(self, service: LibraryDataService) -> None:
        """Bind the existing publication reader and a bounded decoded-source cache."""
        self._service = service
        self._cache: dict[EntityKind, tuple[str, tuple[LibraryEntry, ...]]] = {}

    def read(self) -> LibraryCatalog:
        """Acquire three collections from one manifest and expose partial coverage.

        Returns:
            Immutable catalog with checksummed provenance for each collection.

        Raises:
            LibraryDataError: The manifest is unavailable or changed during reads.
            OSError: Independent temporary storage cannot be created.
        """
        snapshot = self._service.snapshot()
        sources = []
        entries: list[LibraryEntry] = []
        with TemporaryDirectory(prefix="spotify-collections-") as directory:
            for name, kind in COLLECTIONS:
                source, items = self._collection(snapshot, name, kind, Path(directory))
                sources.append(source)
                entries.extend(items)
        identities = []
        for item in sources:
            identities.append((item.sha256, item.state))
        identity = json.dumps([snapshot.revision, identities])
        token = "l1-" + hashlib.sha256(identity.encode()).hexdigest()
        return LibraryCatalog(token, snapshot.revision, tuple(sources), tuple(entries))

    def _collection(
        self,
        snapshot: LibraryDataSnapshot,
        name: ArtifactName,
        kind: EntityKind,
        root: Path,
    ) -> tuple[MirrorSource, tuple[LibraryEntry, ...]]:
        metadata = artifact_metadata(snapshot.document, name)
        if metadata is None:
            return _source(kind, None, "missing"), ()
        cached = self._cache.get(kind)
        if cached is not None and cached[0] == metadata.sha256:
            count = len({item.uri for item in cached[1]})
            return _source(kind, metadata, "ready", count), cached[1]
        try:
            path = root / metadata.filename
            self._service.export_at_snapshot(name, path, snapshot)
            entries = _decode(path, kind)
        except LibraryDataConflictError:
            raise
        except LibraryDataError, OSError, ValueError, TypeError:
            return _source(kind, metadata, "error"), ()
        count = len({item.uri for item in entries})
        self._cache[kind] = metadata.sha256, entries
        return _source(kind, metadata, "ready", count), entries
