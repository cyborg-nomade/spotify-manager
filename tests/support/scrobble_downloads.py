"""Isolated canonical history and real local artifact storage for download checks."""

from dataclasses import dataclass
from pathlib import Path

from spotify_manager.core.library_data.models import ARTIFACT_FILENAMES
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)
from spotify_manager.infrastructure.scrobble_downloads import ScrobbleHistoryFiles


HISTORY = (
    b'{\n  "user": "listener", "scrobbles": '
    b'[{"artist": "Bj\xc3\xb6rk", "track": "Joga"}]\n}\n'
)
NEW_HISTORY = b'{"user":"listener","scrobbles":[{"track":"A newer play"}]}\n'


@dataclass(frozen=True)
class DownloadFixture:
    """Collect the independently owned working, durable and download resources.

    Args:
        store: Real compressed artifact backend.
        service: Existing publication and revision authority.
        files: Snapshot acquisition resource.
        working: Mutable history file used by synchronization.
        spool: Parent containing only temporary download directories.
    """

    store: JsonLibraryDataStore
    service: LibraryDataService
    files: ScrobbleHistoryFiles
    working: Path
    spool: Path


def download_fixture(
    root: Path, store: JsonLibraryDataStore | None = None
) -> DownloadFixture:
    """Create isolated canonical paths and a separate download spool.

    Args:
        root: Test-owned working directory.
        store: Optional deliberately interleaved or faulting local backend.

    Returns:
        Independent resources without publishing an artifact yet.
    """
    paths: dict[ArtifactName, Path] = {}
    for name, filename in ARTIFACT_FILENAMES.items():
        paths[name] = root / "working" / filename
    paths["scrobbles"].parent.mkdir(parents=True)
    spool = root / "spool"
    spool.mkdir()
    backend = store or JsonLibraryDataStore(root / "durable")
    service = LibraryDataService(backend, paths)
    return DownloadFixture(
        backend,
        service,
        ScrobbleHistoryFiles(service, spool),
        paths["scrobbles"],
        spool,
    )


def publish_history(fixture: DownloadFixture, payload: bytes = HISTORY) -> None:
    """Publish valid exact bytes using the ordinary service, as sync would.

    Args:
        fixture: Test-owned canonical resource set.
        payload: Complete JSON payload, preserving its original formatting.
    """
    fixture.working.write_bytes(payload)
    fixture.service.publish("scrobbles", source="download test")
