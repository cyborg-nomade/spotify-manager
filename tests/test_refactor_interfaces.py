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
