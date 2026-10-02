"""Record original deployment export precedence and native decoding failures."""

import base64
import binascii
import gzip
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from spotify_manager.application.historical_values import LastFmExportError
from spotify_manager.routines.blast_from_past import load_scrobble_export
from tests.support.effects import Json
from tests.support.effects import encode_value


@dataclass(frozen=True)
class ExportScenario:
    """Choose an original export source and decoding profile.

    Args:
        source: Original plain, gzip, binary or encoded source.
        profile: Original raw container/byte boundary.
    """

    source: str
    profile: str


def export_scenarios() -> list[ExportScenario]:
    """Enumerate original source precedence and error combinations.

    Returns:
        Stable original source/codec matrix.
    """
    result = []
    for source in ("plain", "gzip", "binary", "encoded"):
        for profile in (
            "valid",
            "null",
            "root-array",
            "missing-array",
            "wrong-array",
            "invalid-json",
            "empty",
            "invalid-unicode",
            "missing",
            "corrupt",
            "valid-fallback",
        ):
            result.append(ExportScenario(source, profile))
    return result


def source_bytes(profile: str) -> bytes:
    """Supply the original unvalidated export source bytes.

    Args:
        profile: Original selected codec profile.

    Returns:
        Original raw content.
    """
    values = {
        "valid": b'{"scrobbles": []}',
        "null": b"null",
        "root-array": b"[]",
        "missing-array": b"{}",
        "wrong-array": b'{"scrobbles": null}',
        "invalid-json": b"broken",
        "empty": b"",
        "invalid-unicode": b"\xff",
    }
    return values.get(profile, values["valid"])


def write_source(
    path: Path, source: str, content: bytes, corrupt: bool = False
) -> None:
    """Write one original deployment source without changing its naming contract.

    Args:
        path: Original primary export path.
        source: Original source family.
        content: Original raw JSON bytes.
        corrupt: Corrupt original compressed or encoded bytes.
    """
    if source == "plain":
        path.write_bytes(b"bad" if corrupt else content)
        return
    compressed = b"corrupt" if corrupt else gzip.compress(content, mtime=0)
    if source == "gzip":
        Path(f"{path}.gz").write_bytes(compressed)
        return
    suffix = "gz.part-aa" if source == "binary" else "gz.b64.part-aa"
    encoded = b"A" if corrupt else base64.b64encode(compressed)
    part = path.parent / f"{path.name}.{suffix}"
    part.write_bytes(compressed if source == "binary" else encoded)


def observe_export(
    scenario: ExportScenario,
    root: Path,
    load: Callable[[Path], dict[str, object]] = load_scrobble_export,
) -> Json:
    """Capture original outcome and cause after each source/fallback boundary.

    Args:
        scenario: Original source and raw profile.
        root: Isolated managed directory.
        load: Original source codec or migrated compatibility entry point.

    Returns:
        Original complete result or native/translated failure.
    """
    path = root / "history.json"
    if scenario.profile != "missing":
        write_source(
            path,
            scenario.source,
            source_bytes(scenario.profile),
            scenario.profile == "corrupt",
        )
    if scenario.profile == "valid-fallback":
        path.write_text("null")
        write_source(path, "gzip", b"null")
        write_source(path, "binary", b"null")
        write_source(path, "encoded", source_bytes("valid"))
    try:
        outcome: object = {"result": load(path)}
    except (
        LastFmExportError,
        UnicodeError,
        OSError,
        EOFError,
        binascii.Error,
        zlib.error,
    ) as error:
        outcome = {
            "error": type(error).__name__,
            "message": str(error),
            "cause": type(error.__cause__).__name__ if error.__cause__ else None,
        }
    return encode_value(outcome, root)
