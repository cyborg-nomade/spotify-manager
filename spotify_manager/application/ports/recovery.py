"""Narrow contracts for recovery facts, durable effects, and presentation."""

from typing import Protocol

from spotify_manager.application.recovery_values import RecoveryAlbum
from spotify_manager.application.recovery_values import RecoveryState
from spotify_manager.application.recovery_values import RecoverySummary
from spotify_manager.application.recovery_values import RemovedAlbumRecord
from spotify_manager.domain.library import AlbumArtist


class RecoveryLibrary(Protocol):
    """Run-scoped observations, follow checks, and ordered durable effects."""

    def load(self) -> tuple[list[RemovedAlbumRecord], RecoveryState]:
        """Load records, progress, and mirror inputs in their original order.

        Returns:
            Review records and mutable completed-work state.
        """

    def albums(
        self, records: list[RemovedAlbumRecord]
    ) -> tuple[RecoveryAlbum | None, ...]:
        """Read one original-size batch, including excess response entries.

        Args:
            records: Ordered requested records.

        Returns:
            Parsed observations padded with unavailable entries when short.
        """

    def follow_artists(
        self, artists: list[AlbumArtist], state: RecoveryState, dry_run: bool
    ) -> tuple[int, int]:
        """Check credited artists with original batching and persistence timing.

        Args:
            artists: Ordered observations, including duplicates across albums.
            state: Current completed-work state.
            dry_run: Preview without remote or durable writes.

        Returns:
            Checked and newly followed artist counts.
        """

    def saved(self, record: RemovedAlbumRecord) -> bool:
        """Read current saved status for a future release.

        Args:
            record: Original removal-log identity and label.

        Returns:
            Existing truthy first-status interpretation.
        """

    def restore(self, record: RemovedAlbumRecord) -> None:
        """Restore one future album using the original retry policy.

        Args:
            record: Original removal-log identity and label.
        """

    def record_album(self, album: RecoveryAlbum, record: RemovedAlbumRecord) -> bool:
        """Update the mirror and statistics after a future-release check.

        Args:
            album: Parsed Spotify observations.
            record: Original removal-log identity and fallback labels.

        Returns:
            Whether the local album mirror gained this album.
        """

    def audit(self, event: dict[str, object]) -> None:
        """Append the original album event before marking it complete.

        Args:
            event: Existing heterogeneous JSON audit document.
        """


class RecoveryPresentation(Protocol):
    """User-facing recovery output, independent of orchestration."""

    def unavailable(self, record: RemovedAlbumRecord) -> None:
        """Show an unavailable album.

        Args:
            record: Original identity and labels.
        """

    def credits(self, album: RecoveryAlbum, record: RemovedAlbumRecord) -> None:
        """Show multiple credited artists.

        Args:
            album: Observations with multiple distinct artists.
            record: Original fallback labels.
        """

    def future(
        self, record: RemovedAlbumRecord, release_date: str | None, status: str
    ) -> None:
        """Show an intended restore, completed restore, or already-saved result.

        Args:
            record: Original removal-log labels.
            release_date: Observed release date.
            status: Existing message prefix.
        """

    def finish(self, summary: RecoverySummary, dry_run: bool) -> None:
        """Present final recovery counts.

        Args:
            summary: Completed outcomes.
            dry_run: Whether the invocation was a preview.
        """
