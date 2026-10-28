"""Ensure source moves cannot hide public contract changes from review."""

from pathlib import Path

import pytest

from docs.refactor.check_interfaces import compare_interfaces


ENDPOINT_PAYLOAD = """{
  "direct_http_calls": [{"line": 12, "source": "routine.py",
    "method": "POST", "endpoint": "playlist/items", "expression": "payload=tracks"}],
  "sdk_methods": {"album": {"references": ["routine.py:12"],
    "sdk_calls": ["self._get(album)"]}}, "sdk_version": "2.26.0"
}"""


def _captures(root: Path, endpoints: str) -> tuple[Path, Path]:
    baseline = root / "baseline"
    candidate = root / "candidate"
    baseline.mkdir()
    candidate.mkdir()
    for directory in (baseline, candidate):
        (directory / "openapi.json").write_text('{"contract": true}')
    (baseline / "spotify-endpoints.json").write_text(ENDPOINT_PAYLOAD)
    (candidate / "spotify-endpoints.json").write_text(endpoints)
    return candidate, baseline


def test_interface_checker_accepts_only_endpoint_line_movement(tmp_path: Path) -> None:
    """Ignore source location drift without replacing the frozen inventories.

    Args:
        tmp_path: Directory for synthetic baseline and candidate captures.
    """
    candidate, baseline = _captures(tmp_path, ENDPOINT_PAYLOAD.replace("12", "800"))
    (baseline / "source-inventory.json").write_text("historical source")
    (baseline / "routine-dependencies.md").write_text("historical dependencies")
    assert compare_interfaces(candidate, baseline) == 2


@pytest.mark.parametrize("native_count", [0, 1, 2])
def test_comparison_source_variant_requires_one_native_lookup(
    tmp_path: Path,
    native_count: int,
) -> None:
    """Account for a parallel compatibility path while rejecting duplicate reads.

    Args:
        tmp_path: Synthetic original and candidate evidence.
        native_count: Number of recorded native metadata lookup sites.
    """
    original = ENDPOINT_PAYLOAD.replace(
        "routine.py:12", "spotify_manager/utils/comparison.py:12"
    )
    references = ['"spotify_manager/utils/comparison.py:12"']
    for offset in range(native_count):
        references.append(
            '"spotify_manager/infrastructure/legacy_library_resources.py:'
            + str(50 + offset)
            + '"'
        )
    changed = original.replace(
        '["spotify_manager/utils/comparison.py:12"]',
        "[" + ", ".join(references) + "]",
    )
    candidate, baseline = _captures(tmp_path, changed)
    (baseline / "spotify-endpoints.json").write_text(original)
    if native_count <= 1:
        assert compare_interfaces(candidate, baseline) == 2
        return
    with pytest.raises(AssertionError, match="spotify-endpoints.json"):
        compare_interfaces(candidate, baseline)


@pytest.mark.parametrize(
    "before,after",
    [
        ("POST", "DELETE"),
        ("playlist/items", "playlist/tracks"),
        ("payload=tracks", "payload=[]"),
        ("self._get(album)", "self._get(artist)"),
        ("routine.py", "other.py"),
        ("2.26.0", "3.0.0"),
        ('["routine.py:12"]', '["routine.py:12", "routine.py:13"]'),
    ],
)
def test_interface_checker_rejects_changed_endpoint_contracts(
    tmp_path: Path,
    before: str,
    after: str,
) -> None:
    """Reject changed methods, paths, payloads, SDK calls, sources, or call counts.

    Args:
        tmp_path: Directory for synthetic captures.
        before: Original token in the endpoint contract.
        after: Deliberately changed contract token.
    """
    candidate, baseline = _captures(tmp_path, ENDPOINT_PAYLOAD.replace(before, after))
    with pytest.raises(AssertionError, match="spotify-endpoints.json"):
        compare_interfaces(candidate, baseline)


def test_interface_checker_rejects_public_schema_drift(tmp_path: Path) -> None:
    """Compare public schemas byte-for-byte, retaining their complete contract.

    Args:
        tmp_path: Directory for synthetic captures.
    """
    candidate, baseline = _captures(tmp_path, ENDPOINT_PAYLOAD)
    (candidate / "openapi.json").write_text('{"contract": false}')
    with pytest.raises(AssertionError, match="openapi.json"):
        compare_interfaces(candidate, baseline)


def test_interface_checker_accepts_route_location_movement(tmp_path: Path) -> None:
    """Keep route identity contracts while ignoring non-public source line evidence.

    Args:
        tmp_path: Directory for isolated original and candidate inventories.
    """
    candidate, baseline = _captures(tmp_path, ENDPOINT_PAYLOAD)
    original = '[{"path":"/health","handler":"api.health","source_line":12}]'
    (baseline / "routes.json").write_text(original)
    (candidate / "routes.json").write_text(original.replace("12", "800"))
    assert compare_interfaces(candidate, baseline) == 3


@pytest.mark.parametrize(
    "before,after", [("/health", "/changed"), ("api.health", "api.other")]
)
def test_interface_checker_rejects_route_identity_changes(
    tmp_path: Path, before: str, after: str
) -> None:
    """Reject changed route paths or callable identities even when source lines move.

    Args:
        tmp_path: Directory for isolated captures.
        before: Original route contract token.
        after: Deliberate public contract change.
    """
    candidate, baseline = _captures(tmp_path, ENDPOINT_PAYLOAD)
    original = '[{"path":"/health","handler":"api.health","source_line":12}]'
    (baseline / "routes.json").write_text(original)
    (candidate / "routes.json").write_text(original.replace(before, after))
    with pytest.raises(AssertionError, match="routes.json"):
        compare_interfaces(candidate, baseline)


@pytest.mark.parametrize("payload", ["tracks", "[]"])
def test_interface_checker_normalizes_only_partial_wrapper(
    tmp_path: Path, payload: str
) -> None:
    """Preserve payload checks when replacing partials with direct SDK calls.

    Args:
        tmp_path: Directory for synthetic captures.
        payload: Unchanged or deliberately modified request payload.
    """
    original = ENDPOINT_PAYLOAD.replace(
        "payload=tracks", "partial(sp._post, 'playlist/items', payload=tracks)"
    )
    direct = ENDPOINT_PAYLOAD.replace(
        "payload=tracks", f"sp._post('playlist/items', payload={payload})"
    )
    candidate, baseline = _captures(tmp_path, direct)
    (baseline / "spotify-endpoints.json").write_text(original)
    if payload == "tracks":
        assert compare_interfaces(candidate, baseline) == 2
        return
    with pytest.raises(AssertionError, match="spotify-endpoints.json"):
        compare_interfaces(candidate, baseline)
