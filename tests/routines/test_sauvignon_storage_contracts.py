"""Freeze original Sauvignon audit bytes and physical-line failure diagnostics."""

import json
from pathlib import Path

import pytest

from spotify_manager.routines import sauvignon as legacy
from tests.support.sauvignon_run import STAMP
from tests.support.sauvignon_run import WEEK
from tests.support.sauvignon_run import option
from tests.support.sauvignon_run import recommendation


def summary() -> legacy.SauvignonSummary:
    """Construct the original completed record with omitted internal evidence.

    Returns:
        A deterministic accepted album result.
    """
    result = legacy.SauvignonResult(
        recommendation(),
        option(),
        legacy.FirstTrack("first", "uri", "Opening"),
        "added",
    )
    return legacy.SauvignonSummary(
        STAMP, WEEK, "destination", 2, 3, 4, 5, 6, 7, 8, 9, 10, False, False, (result,)
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"results": []}', set()),
        ('{"results": [null, {"action": "skipped"}]}', set()),
        (
            '{"results": [{"action": "added", "album": {"artist":null,"album":12}}]}',
            {("none", "12")},
        ),
    ],
)
def test_original_tolerant_records(
    tmp_path: Path, raw: str, expected: set[tuple[str, str]]
) -> None:
    """Protect original skipped result rows and string coercion.

    Args:
        tmp_path: Isolated audit location.
        raw: Original serialized record.
        expected: Original accepted album keys.
    """
    path = tmp_path / "audit"
    path.write_text("\n" + raw + "\n")
    assert legacy.previously_added_album_keys(path) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        "{}",
        '{"results": null}',
        '{"results": [{"action": "added"}]}',
        '{"results": [{"action": "added", "album": {}}]}',
    ],
)
def test_original_invalid_line(tmp_path: Path, raw: str) -> None:
    """Protect blank physical lines and original narrowed error causes.

    Args:
        tmp_path: Isolated audit location.
        raw: Invalid original record.
    """
    path = tmp_path / "audit"
    path.write_text('\n{"results": []}\n' + raw + "\n")
    with pytest.raises(legacy.SauvignonStateError) as failure:
        legacy.previously_added_album_keys(path)
    assert str(failure.value) == f"Sauvignon audit log is invalid at line 3: {path}"
    assert isinstance(failure.value.__cause__, (KeyError, ValueError, TypeError))


def test_original_audit_bytes(tmp_path: Path) -> None:
    """Compare exact original serialization with its pre-extraction snapshot.

    Args:
        tmp_path: Isolated audit location.
    """
    path = tmp_path / "nested/audit"
    legacy.append_log(summary(), path)
    fixture = (
        Path(__file__).resolve().parents[1] / "fixtures/refactor/sauvignon_audit.json"
    )
    expected = json.loads(fixture.read_text())["audit_text"]
    assert path.read_text() == expected
    assert legacy.previously_added_album_keys(path) == {("new", "one")}
    legacy.append_log(summary(), path)
    assert path.read_text() == expected * 2


def test_original_missing_and_directory(tmp_path: Path) -> None:
    """Protect missing logs and read/write OS error translations.

    Args:
        tmp_path: Isolated audit location.
    """
    assert legacy.previously_added_album_keys(tmp_path / "missing") == set()
    with pytest.raises(
        legacy.SauvignonStateError, match="audit log is invalid"
    ) as read:
        legacy.previously_added_album_keys(tmp_path)
    assert isinstance(read.value.__cause__, OSError)
    with pytest.raises(
        legacy.SauvignonStateError, match="Could not write Sauvignon log"
    ) as write:
        legacy.append_log(summary(), tmp_path)
    assert isinstance(write.value.__cause__, OSError)
