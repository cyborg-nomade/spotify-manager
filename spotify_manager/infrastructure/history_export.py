"""Original Last.fm JSON and deployment fallbacks with staged tolerant decoding."""

import base64
import binascii
import gzip
import json
from collections.abc import Callable
from datetime import date
from datetime import datetime
from datetime import tzinfo
from pathlib import Path
from typing import cast

from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure.scrobble_lookup import checked_row
from spotify_manager.infrastructure.scrobble_lookup import checked_timestamp


def load_export(path: Path) -> dict[str, object]:
    """Observe original plain, gzip, binary and encoded fallbacks in order.

    Args:
        path: Original primary export path.

    Returns:
        Original shallowly validated export object.

    Raises:
        LastFmExportError: Original fallback reads or final container validation fail.
    """
    compressed = Path(f"{path}.gz")
    binary = tuple(sorted(path.parent.glob(f"{path.name}.gz.part-*")))
    encoded = tuple(sorted(path.parent.glob(f"{path.name}.gz.b64.part-*")))
    failures: list[str] = []
    payload = _read_plain(path, failures)
    if payload is None and compressed.exists():
        payload = _read_gzip(compressed, failures)
    if payload is None and binary:
        payload = _read_parts(binary, failures, False)
    if payload is None and encoded:
        payload = _read_parts(encoded, failures, True)
    if payload is None:
        raise LastFmExportError("Last.fm export failed: " + "; ".join(failures))
    if not isinstance(payload, dict) or not isinstance(payload.get("scrobbles"), list):
        raise LastFmExportError(
            f"Last.fm export must contain a 'scrobbles' list: {path}"
        )
    return cast(dict[str, object], payload)


def _read_plain(path: Path, failures: list[str]) -> object:
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except OSError as error:
        failures.append(f"could not read {path}: {error}")
    except json.JSONDecodeError as error:
        failures.append(_json_failure(str(path), error))
    return None


def _read_gzip(path: Path, failures: list[str]) -> object:
    try:
        with gzip.open(path, mode="rt", encoding="utf-8") as stream:
            return json.load(stream)
    except OSError as error:
        failures.append(f"could not read {path}: {error}")
    except json.JSONDecodeError as error:
        failures.append(_json_failure(str(path), error))
    return None


def _json_failure(source: str, error: json.JSONDecodeError) -> str:
    return (
        f"{source} is not valid JSON: {error.msg} "
        f"at line {error.lineno}, column {error.colno}"
    )


def _read_parts(paths: tuple[Path, ...], failures: list[str], encoded: bool) -> object:
    label = "encoded" if encoded else "compressed"
    errors = (
        (OSError, UnicodeError, binascii.Error) if encoded else (OSError, UnicodeError)
    )
    try:
        content = _join_parts(paths)
        compressed = base64.b64decode(content) if encoded else content
        return json.loads(gzip.decompress(compressed))
    except errors as error:
        failures.append(
            f"could not read {label} Last.fm export parts {paths[0].parent}: {error}"
        )
    except json.JSONDecodeError as error:
        failures.append(
            f"{label} Last.fm export parts are not valid JSON: "
            f"{error.msg} at line {error.lineno}, column {error.colno}"
        )
    return None


def _join_parts(paths: tuple[Path, ...]) -> bytes:
    contents = []
    for path in paths:
        contents.append(path.read_bytes())
    return b"".join(contents)


def by_date(
    load: Callable[[Path], dict[str, object]], path: Path, timezone: tzinfo
) -> dict[date, list[Scrobble]]:
    """Decode original rows into local date buckets, retaining stable newest-first ties.

    Args:
        load: Original public export codec seam.
        path: Original caller-owned source path.
        timezone: Original local calendar timezone.

    Returns:
        Original ordered scrobbles by local date.

    Raises:
        LastFmExportError: Original row or timestamp decoding fails.
    """
    payload = load(path)
    rows = payload["scrobbles"]
    assert isinstance(rows, list)
    result: dict[date, list[Scrobble]] = {}
    for index, raw in enumerate(rows):
        row = checked_row(raw, index)
        timestamp = checked_timestamp(row, index)
        played = _played_at(timestamp, index, timezone)
        scrobble = Scrobble(
            str(row.get("track") or "Unknown track"),
            str(row.get("artist") or "Unknown artist"),
            str(row.get("album") or ""),
            timestamp,
        )
        result.setdefault(played.date(), []).append(scrobble)
    for scrobbles in result.values():
        scrobbles.sort(key=_timestamp, reverse=True)
    return result


def _timestamp(scrobble: Scrobble) -> int:
    return scrobble.timestamp_ms


def _played_at(timestamp: int, index: int, timezone: tzinfo) -> datetime:
    try:
        return datetime.fromtimestamp(timestamp / 1000, timezone)
    except (OSError, OverflowError, ValueError) as error:
        raise LastFmExportError(
            f"Scrobble {index} has an out-of-range timestamp."
        ) from error
