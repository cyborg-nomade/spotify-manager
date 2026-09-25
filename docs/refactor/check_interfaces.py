"""Compare a candidate capture to the frozen public contracts after source moves.

Capture first with capture_baseline.py --write --output <candidate-directory>.
The original baseline and its source/dependency inventories remain unchanged.
"""

import argparse
import json
import re
from pathlib import Path
from typing import cast


type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
BASELINE = Path(__file__).parent / "baseline"
SOURCE_REPORTS = {"source-inventory.json", "routine-dependencies.md"}
ENDPOINTS = "spotify-endpoints.json"


def _normalize_sequence(items: list[Json]) -> list[Json]:
    result = []
    for item in items:
        result.append(_without_source_lines(item))
    return result


def _without_source_lines(value: Json) -> Json:
    """Remove location-only evidence from Spotify endpoint comparisons.

    Args:
        value: Decoded endpoint inventory.

    Returns:
        The same contracts without line numbers; file paths and reference counts
        remain, as do methods, expressions, parameters, and SDK implementations.
    """
    if isinstance(value, str):
        return re.sub(r"(?<=\.py):[0-9]+$", "", value)
    if isinstance(value, list):
        return _normalize_sequence(value)
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key != "line":
            result[key] = _without_source_lines(item)
    return result


def _endpoint_contracts(path: Path) -> Json:
    payload = cast(Json, json.loads(path.read_text()))
    return _without_source_lines(payload)


def compare_interfaces(candidate: Path, baseline: Path = BASELINE) -> int:
    """Require unchanged public snapshots and semantic Spotify call contracts.

    Args:
        candidate: Directory produced by the existing baseline capture tool.
        baseline: Frozen interface baseline, kept intact throughout the refactor.

    Returns:
        Number of checked public artifacts.

    Raises:
        AssertionError: A public contract differs or a candidate artifact is absent.
        OSError: An artifact cannot be read.
        ValueError: Endpoint JSON cannot be decoded.
    """
    checked = 0
    for path in sorted(baseline.iterdir()):
        if path.name in SOURCE_REPORTS or path.name == ENDPOINTS:
            continue
        assert (candidate / path.name).read_bytes() == path.read_bytes(), path.name
        checked += 1
    assert _endpoint_contracts(candidate / ENDPOINTS) == _endpoint_contracts(
        baseline / ENDPOINTS
    ), ENDPOINTS
    return checked + 1


def main() -> None:
    """Validate a separately captured directory and report contract parity.

    Raises:
        AssertionError: A captured public contract differs from the baseline.
        OSError: An artifact cannot be read.
        ValueError: Endpoint JSON cannot be decoded.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    count = compare_interfaces(args.candidate)
    print(f"Verified {count} public artifacts; source inventories stay frozen.")


if __name__ == "__main__":
    main()
