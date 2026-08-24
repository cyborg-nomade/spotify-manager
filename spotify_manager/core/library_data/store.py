"""Persistence port for durable canonical library files."""

from pathlib import Path
from typing import Protocol

from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataSnapshot


class LibraryDataStore(Protocol):
    """Read, restore, and atomically publish versioned artifacts."""

    def read(self) -> LibraryDataSnapshot:
        """Return the current manifest and immutable store revision."""

    def restore(
        self,
        name: ArtifactName,
        metadata: ArtifactMetadata,
        *,
        revision: str,
        destination: Path,
    ) -> None:
        """Restore one uncompressed artifact at the requested revision."""

    def write(
        self,
        name: ArtifactName,
        payload: bytes,
        manifest: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> LibraryDataSnapshot:
        """Publish one artifact and manifest with a revision guard."""
