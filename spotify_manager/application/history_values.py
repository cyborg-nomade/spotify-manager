"""Stable history refresh results and errors, independent of external clients."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from spotify_manager.domain.history import Scrobble


class ScrobbleHistoryError(RuntimeError):
    """Raised when the canonical Last.fm record cannot be updated safely."""


class ScrobbleHistoryCancelledError(ScrobbleHistoryError):
    """Raised when a history refresh stops at a persistence boundary."""


@dataclass(frozen=True)
class ScrobbleHistorySummary:
    """One complete in-memory or persisted history refresh.

    Args:
        checked_at: Effective UTC refresh timestamp.
        username: Validated export account or requested fallback name.
        history: Complete merged plays in stable timestamp order.
        export_scrobbles: Original record count before merging or rebuilding.
        legacy_scrobbles_added: Additional occurrences from the legacy delta.
        live_scrobbles_added: Additional occurrences from the live API.
        dry_run: Whether persistence was suppressed.
        persisted: Whether the canonical export was replaced.
        backup_path: Created backup, if the export was replaced.
    """

    checked_at: datetime
    username: str
    history: tuple[Scrobble, ...]
    export_scrobbles: int
    legacy_scrobbles_added: int
    live_scrobbles_added: int
    dry_run: bool
    persisted: bool
    backup_path: Path | None

    @property
    def total_scrobbles(self) -> int:
        """Return the merged canonical history size.

        Returns:
            Number of plays, including repeated occurrences.
        """
        return len(self.history)
