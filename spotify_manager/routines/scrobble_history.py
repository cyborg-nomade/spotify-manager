"""Maintain one canonical Last.fm scrobble history for every routine."""

import gzip
import json
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import Protocol
from typing import cast

# UFI
from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.routines import blast_from_past


FILES_DIR = Path(__file__).resolve().parent.parent / "files"
DEFAULT_SCROBBLES_PATH = blast_from_past.DEFAULT_SCROBBLES_PATH
DEFAULT_LEGACY_DELTA_PATH = FILES_DIR / "found_art_recent_scrobbles.jsonl"
DEFAULT_BACKUP_DIR = FILES_DIR / "lastfm_history_backups"
DEFAULT_LOG_PATH = FILES_DIR / "scrobble_history_update_log.jsonl"
ProgressCallback = Callable[[str], None]


class ScrobbleHistoryError(RuntimeError):
    """Raised when the canonical Last.fm record cannot be updated safely."""


class LastFmReader(Protocol):
    """Read the dated Last.fm scrobbles required by history refreshes."""

    def recent_tracks(
        self,
        *,
        from_timestamp: int,
        to_timestamp: int,
        limit: int = 200,
    ) -> tuple[LastFmRecentTrack, ...]:
        """Return all dated scrobbles in a closed UTC range."""


@dataclass(frozen=True)
class ScrobbleHistorySummary:
    """One complete in-memory or persisted history refresh."""

    checked_at: datetime
    username: str
    history: tuple[blast_from_past.Scrobble, ...]
    export_scrobbles: int
    legacy_scrobbles_added: int
    live_scrobbles_added: int
    dry_run: bool
    persisted: bool
    backup_path: Path | None

    @property
    def total_scrobbles(self) -> int:
        """Return the merged canonical history size."""
        return len(self.history)


def _normalized_event_key(
    timestamp_ms: int,
    artist: str,
    track: str,
    album: str,
) -> tuple[int, str, str, str]:
    """Return a stable identity for export, delta, and API overlap."""
    return (
        timestamp_ms,
        blast_from_past.normalize_name(artist),
        blast_from_past.normalize_name(track),
        blast_from_past.normalize_name(album),
    )


def _parse_export_record(raw: object, index: int) -> dict[str, object]:
    """Validate one export record while preserving its extra fields."""
    if not isinstance(raw, dict):
        raise ScrobbleHistoryError(f"Scrobble {index} is not an object.")
    artist = str(raw.get("artist") or "").strip()
    track = str(raw.get("track") or "").strip()
    album = str(raw.get("album") or "").strip()
    raw_timestamp = raw.get("date")
    if isinstance(raw_timestamp, bool) or not isinstance(raw_timestamp, (int, str)):
        raise ScrobbleHistoryError(
            f"Scrobble {index} has no valid millisecond timestamp."
        )
    try:
        timestamp_ms = int(raw_timestamp)
    except (TypeError, ValueError) as exc:
        raise ScrobbleHistoryError(
            f"Scrobble {index} has no valid millisecond timestamp."
        ) from exc
    if not artist or not track or timestamp_ms < 0:
        raise ScrobbleHistoryError(
            f"Scrobble {index} has no valid artist, track, or timestamp."
        )
    record = dict(raw)
    record.update(
        {
            "track": track,
            "artist": artist,
            "album": album,
            "date": timestamp_ms,
        }
    )
    return record


def _load_export(
    path: Path,
) -> tuple[dict[str, object], list[dict[str, object]], bool]:
    """Load and validate the writable canonical Last.fm export."""
    recovered_from_fallback = False
    try:
        with path.open(encoding="utf-8") as export_file:
            payload = json.load(export_file)
    except OSError, json.JSONDecodeError:
        try:
            payload = blast_from_past.load_scrobble_export(path)
        except blast_from_past.LastFmExportError as exc:
            raise ScrobbleHistoryError(str(exc)) from exc
        recovered_from_fallback = True
    if not isinstance(payload, dict) or not isinstance(payload.get("scrobbles"), list):
        raise ScrobbleHistoryError(
            f"Last.fm history must contain a 'scrobbles' list: {path}"
        )
    records = [
        _parse_export_record(raw, index)
        for index, raw in enumerate(payload["scrobbles"])
    ]
    return payload, records, recovered_from_fallback


def _load_legacy_delta(path: Path | None) -> tuple[dict[str, object], ...]:
    """Load the old Found Art delta so it can be absorbed without loss."""
    if path is None or not path.exists():
        return ()
    records: list[dict[str, object]] = []
    try:
        with path.open(encoding="utf-8") as delta_file:
            for line_number, line in enumerate(delta_file, start=1):
                if not line.strip():
                    continue
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError("record is not an object")
                records.append(
                    _parse_export_record(
                        {
                            "artist": raw.get("artist"),
                            "track": raw.get("track"),
                            "album": raw.get("album") or "",
                            "albumId": "",
                            "date": raw.get("timestamp_ms"),
                        },
                        line_number,
                    )
                )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ScrobbleHistoryError(
            f"Legacy Found Art scrobble delta is invalid: {path}"
        ) from exc
    return tuple(records)


def _record_key(record: dict[str, object]) -> tuple[int, str, str, str]:
    """Return the normalized event key for one validated record."""
    return _normalized_event_key(
        cast(int, record["date"]),
        str(record["artist"]),
        str(record["track"]),
        str(record.get("album") or ""),
    )


def _api_record(track: LastFmRecentTrack) -> dict[str, object]:
    """Convert one Last.fm API item to the export schema."""
    return {
        "track": track.track,
        "artist": track.artist,
        "album": track.album,
        "albumId": "",
        "date": track.timestamp_seconds * 1000,
    }


def _history(records: list[dict[str, object]]) -> tuple[blast_from_past.Scrobble, ...]:
    """Convert ordered export records to the shared normalized model."""
    return tuple(
        blast_from_past.Scrobble(
            track=str(record["track"]),
            artist=str(record["artist"]),
            album=str(record.get("album") or ""),
            timestamp_ms=cast(int, record["date"]),
        )
        for record in records
    )


def _backup_export(
    path: Path,
    backup_dir: Path,
    checked_at: datetime,
    recovered_payload: dict[str, object] | None = None,
) -> Path:
    """Create a compressed timestamped backup before replacing the export."""
    stamp = checked_at.strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"{path.stem}-{stamp}.json.gz"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        if recovered_payload is None:
            with path.open("rb") as source, gzip.open(backup_path, "wb") as target:
                shutil.copyfileobj(source, target)
        else:
            with gzip.open(backup_path, "wt", encoding="utf-8") as target:
                json.dump(
                    recovered_payload,
                    target,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
    except OSError as exc:
        raise ScrobbleHistoryError(
            f"Could not back up Last.fm history to {backup_path}."
        ) from exc
    return backup_path


def _write_export_atomic(
    path: Path,
    payload: dict[str, object],
    records: list[dict[str, object]],
) -> None:
    """Replace the canonical export only after a complete temporary write."""
    updated_payload = dict(payload)
    updated_payload["scrobbles"] = records
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            json.dump(
                updated_payload,
                temporary,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ScrobbleHistoryError(
            f"Could not atomically update Last.fm history: {path}"
        ) from exc


def _append_log(summary: ScrobbleHistorySummary, path: Path) -> None:
    """Append one compact audit record after a real refresh."""
    record = {
        "checked_at": summary.checked_at.isoformat(),
        "username": summary.username,
        "export_scrobbles": summary.export_scrobbles,
        "legacy_scrobbles_added": summary.legacy_scrobbles_added,
        "live_scrobbles_added": summary.live_scrobbles_added,
        "total_scrobbles": summary.total_scrobbles,
        "persisted": summary.persisted,
        "backup_path": str(summary.backup_path) if summary.backup_path else None,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ScrobbleHistoryError(
            f"Could not write Last.fm history audit log: {path}"
        ) from exc


def _mark_export_checked(path: Path, checked_at: datetime) -> None:
    """Record a successful live check without rewriting unchanged history."""
    try:
        current = path.stat()
        os.utime(path, (current.st_atime, checked_at.timestamp()))
    except OSError as exc:
        raise ScrobbleHistoryError(
            f"Could not update the Last.fm history check time: {path}"
        ) from exc


def refresh_scrobble_history(
    lastfm: LastFmReader,
    *,
    expected_username: str | None = None,
    export_path: Path = DEFAULT_SCROBBLES_PATH,
    legacy_delta_path: Path | None = DEFAULT_LEGACY_DELTA_PATH,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    log_path: Path = DEFAULT_LOG_PATH,
    dry_run: bool = False,
    now: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ScrobbleHistorySummary:
    """Fetch a complete API delta and safely merge it into the shared export."""
    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    if progress_callback is not None:
        progress_callback("Loading the canonical Last.fm history")
    payload, export_records, recovered_from_fallback = _load_export(export_path)
    if recovered_from_fallback and progress_callback is not None:
        progress_callback("Recovered Last.fm history from compressed fallback parts")
    username = str(payload.get("username") or "").strip()
    if (
        expected_username
        and username
        and username.casefold() != expected_username.casefold()
    ):
        raise ScrobbleHistoryError(
            f"Last.fm export belongs to {username}, not {expected_username}."
        )
    username = username or (expected_username or "")

    records = list(export_records)
    known_counts = Counter(_record_key(record) for record in records)
    legacy_added = 0
    legacy_seen: Counter[tuple[int, str, str, str]] = Counter()
    for record in _load_legacy_delta(legacy_delta_path):
        key = _record_key(record)
        legacy_seen[key] += 1
        if legacy_seen[key] <= known_counts[key]:
            continue
        records.append(record)
        legacy_added += 1
    if not records:
        raise ScrobbleHistoryError("The Last.fm scrobble history is empty.")

    known_counts = Counter(_record_key(record) for record in records)
    latest_timestamp_ms = max(cast(int, record["date"]) for record in records)
    from_timestamp = latest_timestamp_ms // 1000
    to_timestamp = int(checked_at.timestamp())
    live_added = 0
    if from_timestamp <= to_timestamp:
        if progress_callback is not None:
            progress_callback("Fetching newer scrobbles from Last.fm")
        live_seen: Counter[tuple[int, str, str, str]] = Counter()
        for live_track in lastfm.recent_tracks(
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        ):
            record = _api_record(live_track)
            key = _record_key(record)
            live_seen[key] += 1
            if live_seen[key] <= known_counts[key]:
                continue
            records.append(record)
            live_added += 1

    records = sorted(
        records,
        key=lambda record: cast(int, record["date"]),
    )
    changed = legacy_added > 0 or live_added > 0
    backup_path: Path | None = None
    persisted = False
    if changed and not dry_run:
        if progress_callback is not None:
            progress_callback("Backing up and atomically saving Last.fm history")
        backup_path = _backup_export(
            export_path,
            backup_dir,
            checked_at,
            recovered_payload=payload if recovered_from_fallback else None,
        )
        _write_export_atomic(export_path, payload, records)
        persisted = True

    summary = ScrobbleHistorySummary(
        checked_at=checked_at,
        username=username,
        history=_history(records),
        export_scrobbles=len(export_records),
        legacy_scrobbles_added=legacy_added,
        live_scrobbles_added=live_added,
        dry_run=dry_run,
        persisted=persisted,
        backup_path=backup_path,
    )
    if not dry_run:
        _mark_export_checked(export_path, checked_at)
        if not changed and progress_callback is not None:
            progress_callback("History already current; recorded successful check time")
        _append_log(summary, log_path)
    return summary
