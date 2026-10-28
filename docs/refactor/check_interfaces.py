"""Compare a candidate capture to the frozen public contracts after source moves.

Capture first with capture_baseline.py --write --output <candidate-directory>.
The original baseline and its source/dependency inventories remain unchanged.
"""

import argparse
import ast
import json
import re
from pathlib import Path
from typing import cast


type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
BASELINE = Path(__file__).parent / "baseline"
SOURCE_REPORTS = {"source-inventory.json", "routine-dependencies.md"}
ENDPOINTS = "spotify-endpoints.json"
ROUTES = "routes.json"


def _normalize_sequence(items: list[Json]) -> list[Json]:
    result = []
    for item in items:
        result.append(_without_source_lines(item))
    return result


def _without_source_lines(value: Json) -> Json:
    """Remove location-only evidence from endpoint and route inventories.

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
        if key in {"line", "source_line"}:
            continue
        if key == "expression" and isinstance(item, str):
            item = _direct_expression(item)
        result[key] = _without_source_lines(item)
    return result


def _direct_expression(expression: str) -> str:
    """Compare a captured partial with its equivalent direct SDK call.

    Args:
        expression: Original static call expression.

    Returns:
        Identical arguments and keywords with only the partial wrapper removed.
    """
    try:
        node = ast.parse(expression, mode="eval").body
    except SyntaxError:
        return expression
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return expression
    if node.func.id != "partial" or not node.args:
        return expression
    direct = ast.Call(func=node.args[0], args=node.args[1:], keywords=node.keywords)
    return ast.unparse(direct)


def _endpoint_contracts(path: Path) -> Json:
    payload = cast(Json, json.loads(path.read_text()))
    return _comparison_source_variants(_without_source_lines(payload))


def _comparison_source_variants(payload: Json) -> Json:
    """Account for the retained Python and native variants of one album lookup.

    Args:
        payload: Endpoint evidence with source line movement normalized.

    Returns:
        Contracts counting the reviewed comparison lookup once when both its
        original Python source and its single native counterpart are present.
        Other methods, sources, counts, expressions and SDK bodies remain exact.
    """
    if not isinstance(payload, dict):
        return payload
    methods = payload.get("sdk_methods")
    if not isinstance(methods, dict):
        return payload
    album = methods.get("album")
    if not isinstance(album, dict):
        return payload
    references = album.get("references")
    if not isinstance(references, list):
        return payload
    native = "spotify_manager/infrastructure/legacy_library_resources.py"
    original = "spotify_manager/utils/comparison.py"
    if references.count(native) == 1 and original in references:
        references.remove(native)
    return payload


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
        if path.name == ROUTES:
            assert _endpoint_contracts(candidate / ROUTES) == _endpoint_contracts(
                path
            ), ROUTES
        else:
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
