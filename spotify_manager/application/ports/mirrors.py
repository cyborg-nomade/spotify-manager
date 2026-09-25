"""Persistence port for durable canonical library files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from typing import Protocol


if TYPE_CHECKING:
    from spotify_manager.core.library_data.models import ArtifactMetadata
    from spotify_manager.core.library_data.models import ArtifactName
    from spotify_manager.core.library_data.models import LibraryDataSnapshot


class LibraryDataStore(Protocol):
    """Read, restore, and atomically publish versioned artifacts."""

    def read(self) -> LibraryDataSnapshot:
        """Read the current manifest at an immutable revision.

        Returns:
            The original manifest snapshot.

        Raises:
            LibraryDataError: The manifest cannot be read or validated.
        """

    def restore(
        self,
        name: ArtifactName,
        metadata: ArtifactMetadata,
        *,
        revision: str,
        destination: Path,
    ) -> None:
        """Restore one uncompressed artifact at the requested revision.

        Args:
            name: Canonical artifact name.
            metadata: Expected artifact metadata from the pinned manifest.
            revision: Immutable store revision.
            destination: Temporary destination checked by the existing service.

        Raises:
            LibraryDataError: The artifact cannot be restored.
        """

    def write(
        self,
        name: ArtifactName,
        payload: bytes,
        manifest: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> LibraryDataSnapshot:
        """Publish one artifact and manifest with a revision guard.

        Args:
            name: Canonical artifact name.
            payload: Validated uncompressed bytes.
            manifest: Complete updated manifest.
            expected_revision: Revision observed before publication.
            message: Existing provenance or commit description.

        Returns:
            The committed manifest snapshot.

        Raises:
            LibraryDataConflictError: Another writer changed the manifest.
            LibraryDataError: Validation or publication fails.
        """
