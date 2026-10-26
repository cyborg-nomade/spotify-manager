"""Adapt the original history files, Last.fm client and managed artifact service."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from spotify_manager.application.history_refresh import HistoryExport
from spotify_manager.application.history_refresh import HistoryRecord
from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.routines import scrobble_history as legacy


@dataclass
class LegacyHistoryStorage:
    """Retain the existing export, backup, mirror and audit boundaries.

    Args:
        export_path: Canonical history path.
        legacy_path: Optional legacy delta path.
        backup_dir: Compressed backup directory.
        log_path: Audit destination.
        data_service: Managed service, resolved during hydration when needed.
    """

    export_path: Path
    legacy_path: Path | None
    backup_dir: Path
    log_path: Path
    data_service: LibraryDataService | None = None

    def hydrate(self) -> None:
        """Hydrate managed history before the first cancellation check."""
        from spotify_manager.bootstrap.library_data import artifact_for_path
        from spotify_manager.bootstrap.library_data import get_library_data_service

        if artifact_for_path(self.export_path) != "scrobbles":
            return
        self.data_service = get_library_data_service()
        self.data_service.hydrate("scrobbles")

    def load(self) -> HistoryExport:
        """Load validated records with original fallback handling.

        Returns:
            Payload, records and fallback provenance.

        Raises:
            ScrobbleHistoryError: The export cannot be read or validated.
        """
        from spotify_manager.routines.scrobble_history import _load_export

        return HistoryExport(*_load_export(self.export_path))

    def legacy(self) -> tuple[HistoryRecord, ...]:
        """Read the optional legacy delta.

        Returns:
            Records in source order.

        Raises:
            ScrobbleHistoryError: A present delta is invalid.
        """
        from spotify_manager.routines.scrobble_history import _load_legacy_delta

        return _load_legacy_delta(self.legacy_path)

    def backup(self, export: HistoryExport, checked_at: datetime) -> Path:
        """Back up original bytes or the recovered fallback payload.

        Args:
            export: Original contents and recovery provenance.
            checked_at: Backup timestamp.

        Returns:
            Created compressed backup path.

        Raises:
            ScrobbleHistoryError: Backup creation fails.
        """
        from spotify_manager.routines.scrobble_history import _backup_export

        return _backup_export(
            self.export_path,
            self.backup_dir,
            checked_at,
            recovered_payload=export.payload if export.recovered else None,
        )

    def write(self, payload: dict[str, object], records: list[HistoryRecord]) -> None:
        """Atomically replace history using the existing serializer.

        Args:
            payload: Export metadata.
            records: Complete ordered history.

        Raises:
            ScrobbleHistoryError: Atomic replacement fails.
        """
        from spotify_manager.routines.scrobble_history import _write_export_atomic

        _write_export_atomic(self.export_path, payload, records)

    def mark(self, checked_at: datetime) -> None:
        """Update the export's successful-check timestamp.

        Args:
            checked_at: Effective refresh time.

        Raises:
            ScrobbleHistoryError: The file timestamp cannot be updated.
        """
        from spotify_manager.routines.scrobble_history import _mark_export_checked

        _mark_export_checked(self.export_path, checked_at)

    def publish(self, full_rebuild: bool) -> None:
        """Publish managed history after its check timestamp is recorded.

        Args:
            full_rebuild: Select the existing publication description.
        """
        if self.data_service is None:
            return
        source = "Last.fm API full rebuild" if full_rebuild else "Last.fm API refresh"
        self.data_service.publish("scrobbles", source=source)

    def audit(self, summary: ScrobbleHistorySummary) -> None:
        """Append the original audit schema after publication.

        Args:
            summary: Completed refresh.

        Raises:
            ScrobbleHistoryError: Audit persistence fails.
        """
        from spotify_manager.routines.scrobble_history import _append_log

        _append_log(summary, self.log_path)


@dataclass(frozen=True)
class LegacyHistoryReader:
    """Read Last.fm records without moving conversion before cancellation.

    Args:
        client: Caller-owned Last.fm client.
    """

    client: legacy.LastFmReader

    def fetch(self, start: int, end: int) -> Iterable[HistoryRecord]:
        """Read the inclusive range and defer record conversion until iteration.

        Args:
            start: First UTC second, inclusive.
            end: Last UTC second, inclusive.

        Returns:
            Lazy records consumed after the workflow's cancellation check.
        """
        from spotify_manager.routines.scrobble_history import _api_record

        tracks = self.client.recent_tracks(from_timestamp=start, to_timestamp=end)
        return map(_api_record, tracks)
