"""Request-owned temporary snapshots of the existing durable history artifact."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from spotify_manager.core.library_data.models import ARTIFACT_FILENAMES
from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.service import LibraryDataService


@dataclass(frozen=True)
class StoredScrobbleDownload:
    """Keep a verified file alive until its response releases it.

    Args:
        directory: Unique request-owned directory.
        metadata: Metadata verified against the restored bytes.
    """

    directory: TemporaryDirectory[str]
    metadata: ArtifactMetadata

    @property
    def path(self) -> Path:
        """Return this snapshot's validated canonical filename.

        Returns:
            An independent temporary history file.
        """
        return Path(self.directory.name) / self.metadata.filename

    def close(self) -> None:
        """Remove the snapshot without touching managed files or published data."""
        self.directory.cleanup()


@dataclass(frozen=True)
class ScrobbleHistoryFiles:
    """Restore history through the shared service into independent temporary files.

    Args:
        service: Existing revision-aware canonical artifact service.
        temporary_root: Optional isolated spool parent, primarily for verification.
    """

    service: LibraryDataService
    temporary_root: Path | None = None

    def prepare(self) -> StoredScrobbleDownload | None:
        """Acquire a verified file and clean up failed or missing preparations.

        Returns:
            Owned snapshot, or None when no scrobble artifact is published.

        Raises:
            LibraryDataError: Restoring or verifying the artifact fails.
            OSError: The temporary directory cannot be created.
        """
        directory = TemporaryDirectory(
            prefix="scrobble-download-", dir=self.temporary_root
        )
        metadata = None
        try:
            path = Path(directory.name) / ARTIFACT_FILENAMES["scrobbles"]
            metadata = self.service.export_snapshot("scrobbles", path)
            if metadata is None:
                return None
            return StoredScrobbleDownload(directory, metadata)
        finally:
            if metadata is None:
                directory.cleanup()
