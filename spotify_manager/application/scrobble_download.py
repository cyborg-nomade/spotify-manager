"""Acquire a verified stored history snapshot without starting synchronization."""

from pathlib import Path
from typing import Protocol

from spotify_manager.core.library_data.models import ArtifactMetadata


class MissingScrobbleHistoryError(RuntimeError):
    """No canonical scrobble artifact has been published for download."""


class ScrobbleDownload(Protocol):
    """Own the verified temporary file until its HTTP response finishes."""

    @property
    def path(self) -> Path:
        """Return the independent, complete snapshot file.

        Returns:
            Request-owned path, never the mutable working history.
        """
        ...

    @property
    def metadata(self) -> ArtifactMetadata:
        """Return the manifest identity verified against this file.

        Returns:
            Original filename, checksum, size and publication metadata.
        """
        ...

    def close(self) -> None:
        """Remove this request's temporary file and directory."""
        ...


class ScrobbleDownloads(Protocol):
    """Acquire independently owned history snapshots through existing storage."""

    def prepare(self) -> ScrobbleDownload | None:
        """Read and verify one complete published history artifact.

        Returns:
            Owned snapshot, or None when no history artifact exists.

        Raises:
            LibraryDataError: Storage or integrity verification fails.
        """
        ...


def prepare_scrobble_history_download(downloads: ScrobbleDownloads) -> ScrobbleDownload:
    """Make missing stored history explicit without falling back to a working copy.

    Args:
        downloads: Named revision-pinned snapshot resource.

    Returns:
        Verified snapshot whose response must release its temporary storage.

    Raises:
        MissingScrobbleHistoryError: No scrobble artifact has been published.
        LibraryDataError: Storage or integrity verification fails.
    """
    snapshot = downloads.prepare()
    if snapshot is None:
        raise MissingScrobbleHistoryError(
            "No stored Last.fm history is available. Sync history first."
        )
    return snapshot
