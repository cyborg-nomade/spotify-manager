"""Refresh canonical listening history through explicit observation and effect ports."""

from collections import Counter
from collections.abc import Callable
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from typing import cast

from spotify_manager.application.history_values import ScrobbleHistoryError
from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name


type HistoryRecord = dict[str, object]


@dataclass(frozen=True)
class HistoryExport:
    """Validated export contents with preserved metadata and recovery provenance.

    Args:
        payload: Original export metadata, including extra fields.
        records: Validated scrobbles in source order.
        recovered: Whether compressed fallback supplied the export.
    """

    payload: dict[str, object]
    records: list[HistoryRecord]
    recovered: bool


class HistoryStorage(Protocol):
    """Observe and persist canonical history using its existing storage semantics."""

    def hydrate(self) -> None:
        """Hydrate managed history before cancellation or local observation."""

    def load(self) -> HistoryExport:
        """Read the validated export.

        Returns:
            Original records and recovery provenance.
        """

    def legacy(self) -> tuple[HistoryRecord, ...]:
        """Read the legacy delta.

        Returns:
            Validated records in their original order.
        """

    def backup(self, export: HistoryExport, checked_at: datetime) -> Path:
        """Back up the original export before replacement.

        Args:
            export: Original contents and fallback flag.
            checked_at: Timestamp for the backup name.

        Returns:
            Created backup path.
        """

    def write(self, payload: dict[str, object], records: list[HistoryRecord]) -> None:
        """Atomically replace the canonical export.

        Args:
            payload: Preserved metadata, with rebuild stamp when requested.
            records: Complete merged history.
        """

    def mark(self, checked_at: datetime) -> None:
        """Record a successful live check.

        Args:
            checked_at: Successful-check timestamp.
        """

    def publish(self, full_rebuild: bool) -> None:
        """Publish managed history, including unchanged successful checks.

        Args:
            full_rebuild: Select the original publication description.
        """

    def audit(self, summary: ScrobbleHistorySummary) -> None:
        """Append the completed real refresh to the audit log.

        Args:
            summary: Accepted refresh effects and merged history.
        """


def _record_key(record: HistoryRecord) -> tuple[int, str, str, str]:
    return (
        _timestamp(record),
        normalize_name(str(record["artist"])),
        normalize_name(str(record["track"])),
        normalize_name(str(record.get("album") or "")),
    )


def _timestamp(record: HistoryRecord) -> int:
    return cast(int, record["date"])


def _merge(records: list[HistoryRecord], incoming: Iterable[HistoryRecord]) -> int:
    known = Counter(_record_key(record) for record in records)
    seen: Counter[tuple[int, str, str, str]] = Counter()
    added = 0
    for record in incoming:
        key = _record_key(record)
        seen[key] += 1
        if seen[key] <= known[key]:
            continue
        records.append(record)
        added += 1
    return added


def _history(records: list[HistoryRecord]) -> tuple[Scrobble, ...]:
    history = []
    for record in records:
        history.append(
            Scrobble(
                track=str(record["track"]),
                artist=str(record["artist"]),
                album=str(record.get("album") or ""),
                timestamp_ms=_timestamp(record),
            )
        )
    return tuple(history)


def _username(payload: dict[str, object], expected: str | None) -> str:
    username = str(payload.get("username") or "").strip()
    if expected and username and username.casefold() != expected.casefold():
        raise ScrobbleHistoryError(
            f"Last.fm export belongs to {username}, not {expected}."
        )
    return username or (expected or "")


@dataclass(frozen=True)
class HistoryRefresh:
    """Merge overlap by occurrence count, then preserve the ordered refresh effects.

    Args:
        storage: Existing file, backup, mirror and audit boundaries.
        fetch: Read live records in an inclusive UTC seconds range.
        clock: Read the effective UTC refresh time after hydration and cancellation.
        check_cancel: Raise the original cancellation error at each boundary.
        progress: Present existing progress messages.
    """

    storage: HistoryStorage
    fetch: Callable[[int, int], Iterable[HistoryRecord]]
    clock: Callable[[], datetime]
    check_cancel: Callable[[], None]
    progress: Callable[[str], None]

    def run(
        self, expected_username: str | None, dry_run: bool, full_rebuild: bool
    ) -> ScrobbleHistorySummary:
        """Refresh history without changing overlap, preview or recovery behavior.

        Args:
            expected_username: Optional account ownership check.
            dry_run: Suppress backup, writes, publication and audit.
            full_rebuild: Replace history from the complete live range.

        Returns:
            Merged history and the accepted persistence effects.

        Raises:
            ScrobbleHistoryError: Ownership or empty-history checks fail.
            ScrobbleHistoryCancelledError: Cancellation is requested.
            OSError: An injected effect fails; earlier effects remain accepted.
        """
        self.storage.hydrate()
        self.check_cancel()
        checked_at = self.clock()
        self.progress("Loading the canonical Last.fm history")
        export = self.storage.load()
        self.check_cancel()
        if export.recovered:
            self.progress("Recovered Last.fm history from compressed fallback parts")
        username = _username(export.payload, expected_username)
        records, legacy_added = self._initial_records(export, full_rebuild)
        live_added = self._fetch(records, checked_at, full_rebuild)
        records = sorted(records, key=_timestamp)
        if full_rebuild and not records and export.records:
            raise ScrobbleHistoryError(
                "Refusing to replace nonempty history with an empty API response."
            )
        changed = full_rebuild or legacy_added > 0 or live_added > 0
        self.check_cancel()
        backup = self._persist(
            export, records, checked_at, full_rebuild, changed and not dry_run
        )
        summary = ScrobbleHistorySummary(
            checked_at,
            username,
            _history(records),
            len(export.records),
            legacy_added,
            live_added,
            dry_run,
            backup is not None,
            backup,
        )
        if not dry_run:
            self._finish(summary, full_rebuild, changed)
        return summary

    def _initial_records(
        self, export: HistoryExport, full_rebuild: bool
    ) -> tuple[list[HistoryRecord], int]:
        records = [] if full_rebuild else list(export.records)
        added = 0
        if not full_rebuild and not export.payload.get("full_rebuilt_at"):
            added = _merge(records, self.storage.legacy())
        if not records and not full_rebuild:
            raise ScrobbleHistoryError("The Last.fm scrobble history is empty.")
        return records, added

    def _fetch(
        self, records: list[HistoryRecord], checked_at: datetime, full_rebuild: bool
    ) -> int:
        latest = max((_timestamp(record) for record in records), default=0)
        start, end = latest // 1000, int(checked_at.timestamp())
        if start > end:
            return 0
        self.progress(
            "Rebuilding all scrobbles from Last.fm"
            if full_rebuild
            else "Fetching newer scrobbles from Last.fm"
        )
        live = self.fetch(start, end)
        self.check_cancel()
        return _merge(records, live)

    def _persist(
        self,
        export: HistoryExport,
        records: list[HistoryRecord],
        checked_at: datetime,
        full_rebuild: bool,
        persist: bool,
    ) -> Path | None:
        if not persist:
            return None
        self.progress("Backing up and atomically saving Last.fm history")
        backup = self.storage.backup(export, checked_at)
        payload = export.payload
        if full_rebuild:
            payload = dict(payload, full_rebuilt_at=checked_at.isoformat())
        self.storage.write(payload, records)
        return backup

    def _finish(
        self, summary: ScrobbleHistorySummary, full_rebuild: bool, changed: bool
    ) -> None:
        self.storage.mark(summary.checked_at)
        self.storage.publish(full_rebuild)
        if not changed:
            self.progress("History already current; recorded successful check time")
        self.storage.audit(summary)
