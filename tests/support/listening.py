"""Independent local publications and hand-calculated listening fixtures."""

import json
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from spotify_manager.core.library_data.models import ARTIFACT_FILENAMES
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import artifact_metadata
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.infrastructure.listening.build import build_listening_index
from spotify_manager.infrastructure.listening.reader import ListeningIndex
from spotify_manager.infrastructure.listening.runtime import ListeningRuntime
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)


def timestamp(value: str) -> int:
    """Convert an explicit UTC fixture timestamp to source milliseconds."""
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


def scrobble(
    when: str, artist: str = "Alpha", track: str = "Song", album: str = "Record"
) -> dict[str, object]:
    """Create one source row, including an opaque source album identifier."""
    return {
        "date": timestamp(when),
        "artist": artist,
        "track": track,
        "album": album,
        "albumId": "source-album-id" if album else "",
    }


def sample_history() -> list[dict[str, object]]:
    """Return seven rows with duplicates, missing albums, and distinct identities."""
    return [
        scrobble("2024-01-01T12:00:00"),
        scrobble("2024-01-01T12:00:00"),
        scrobble("2024-01-02T12:00:00", "ALPHA", "Second", ""),
        scrobble("2024-01-08T12:00:00"),
        scrobble("2024-02-01T12:00:00", "Béta", "Song", "Record"),
        scrobble("2024-03-01T12:00:00", "Beta", "Song", "Record"),
        scrobble("2024-07-01T12:00:00", "Alpha", "Song", "Record"),
    ]


@dataclass(frozen=True)
class ListeningFixture:
    """Own an independent source publication and process-local disposable cache."""

    service: LibraryDataService
    source: Path
    runtime: ListeningRuntime
    root: Path

    def publish(self, rows: list[dict[str, object]]) -> None:
        """Publish a deliberate fixture replacement through real storage checks."""
        self.source.write_text(json.dumps({"username": "fixture", "scrobbles": rows}))
        self.service.publish("scrobbles", source="listening-fixture")

    def index(self) -> ListeningIndex:
        """Build a separate concrete reader without creating an async task."""
        metadata = artifact_metadata(self.service.snapshot().document, "scrobbles")
        assert metadata is not None
        path = self.root / "reader.sqlite"
        metadata_result = build_listening_index(self.source, path, metadata)
        return ListeningIndex(path, metadata_result)


def listening_fixture(
    root: Path, store: JsonLibraryDataStore | None = None
) -> ListeningFixture:
    """Construct a local durable service without touching real library files."""
    paths: dict[ArtifactName, Path] = {}
    for name, filename in ARTIFACT_FILENAMES.items():
        paths[name] = root / filename
    service = LibraryDataService(store or JsonLibraryDataStore(root / "store"), paths)
    directory: TemporaryDirectory[str] = TemporaryDirectory(dir=root)
    runtime = ListeningRuntime(service, directory)
    return ListeningFixture(service, paths["scrobbles"], runtime, root)
