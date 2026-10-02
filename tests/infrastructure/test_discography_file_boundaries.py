"""Verify Discography permissive state, atomic cleanup and exact audit bytes."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from spotify_manager.application.discography_values import DiscographyStateError
from spotify_manager.infrastructure.discography_files import append_log
from spotify_manager.infrastructure.discography_files import default_state
from spotify_manager.infrastructure.discography_files import load_state
from spotify_manager.infrastructure.discography_files import save_next_queue
from spotify_manager.infrastructure.discography_files import validate_state
from spotify_manager.infrastructure.studio_records import artist_pairs
from spotify_manager.infrastructure.studio_records import positive_int
from spotify_manager.infrastructure.studio_records import studio_release
from tests.support.discography_apply import plan
from tests.support.discography_boundaries import raw_release
from tests.support.queue_neighbors import NOW


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"version": 2, "next_queue": "requeue"},
        {"version": 1, "next_queue": "unknown"},
    ],
)
def test_discography_rejects_original_invalid_state(raw: object) -> None:
    """Retain original shallow state validation.

    Args:
        raw: Original invalid root or required authority.
    """
    with pytest.raises(DiscographyStateError, match="state is invalid"):
        validate_state(raw)


def test_discography_state_accepts_boolean_version_and_retains_unknown_fields() -> None:
    """Retain original equality-based version tolerance and complete in-memory state."""
    state: dict[str, object] = {
        "version": True,
        "next_queue": "requeue",
        "extra": "value",
    }
    assert validate_state(state) is state
    assert default_state() == {"version": 1, "next_queue": "requeue"}


@pytest.mark.parametrize("text", ["{", "{}", "null"])
def test_discography_load_errors_retain_original_location(
    tmp_path: Path, text: str
) -> None:
    """Wrap malformed JSON and invalid authority with the original path.

    Args:
        tmp_path: Isolated file location.
        text: Original malformed or invalid content.
    """
    path = tmp_path / "state.json"
    path.write_text(text)
    with pytest.raises(DiscographyStateError, match=str(path)):
        load_state(path)


def test_discography_state_files_replace_complete_record_and_remove_temporary(
    tmp_path: Path,
) -> None:
    """Preserve exact complete replacement bytes and successful temporary cleanup.

    Args:
        tmp_path: Isolated state location.
    """
    path = tmp_path / "nested/state.json"
    assert load_state(path) == default_state()
    save_next_queue("memory_lane", path)
    assert path.read_text() == '{\n  "version": 1,\n  "next_queue": "memory_lane"\n}\n'
    assert not path.with_suffix(".json.tmp").exists()
    assert load_state(path)["next_queue"] == "memory_lane"


def test_discography_failed_replacement_still_removes_temporary(tmp_path: Path) -> None:
    """Retain original cleanup after a failed atomic replacement.

    Args:
        tmp_path: Isolated state location.
    """
    destination = tmp_path / "directory.json"
    destination.mkdir()
    with pytest.raises(DiscographyStateError, match="Could not save"):
        save_next_queue("requeue", destination)
    assert not destination.with_suffix(".json.tmp").exists()
    with pytest.raises(DiscographyStateError, match="state is invalid"):
        load_state(destination)


def test_discography_audit_bytes_retain_complete_release_and_marker_fields(
    tmp_path: Path,
) -> None:
    """Retain original UTF-8 JSON Lines field order and complete selected records.

    Args:
        tmp_path: Isolated audit location.
    """
    selection = plan().artists[0]
    path = tmp_path / "nested/audit.jsonl"
    append_log(selection, "requeue", path, NOW)
    expected = {
        "recorded_at": NOW.isoformat(),
        "artist_id": selection.spotify_id,
        "artist": selection.name,
        "source_queue": selection.source_queue,
        "releases": [asdict(item) for item in selection.releases],
        "markers": [asdict(item) for item in selection.markers],
        "next_queue": "requeue",
    }
    assert path.read_text() == json.dumps(expected, ensure_ascii=False) + "\n"
    with pytest.raises(DiscographyStateError, match="Could not write"):
        append_log(selection, "requeue", tmp_path, NOW)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, 0),
        (False, 0),
        (None, 0),
        (0, 0),
        (-1, 0),
        (4, 4),
        (" 5 ", 5),
        ("invalid", 0),
        ("0", 0),
        ("-1", 0),
    ],
)
def test_shared_studio_count_keeps_original_coercion(
    raw: object, expected: int
) -> None:
    """Retain the shared studio parser's distinct integer/string/boolean policy.

    Args:
        raw: Original untrusted count.
        expected: Original positive count or fallback.
    """
    assert positive_int(raw) == expected


def test_shared_studio_credit_and_candidate_records_keep_original_tolerance() -> None:
    """Retain skipped invalid credits, ID fallback names and required studio URIs."""
    assert artist_pairs(None) == ()
    assert artist_pairs([None, {}, {"id": "a"}]) == (("a", "a"),)
    assert studio_release(None, "artist") is None
    assert studio_release({}, "artist") is None
    assert studio_release(raw_release("a") | {"uri": " "}, "artist") is None
    assert studio_release(raw_release("a", " "), "artist") is None
    assert studio_release(raw_release(" "), "artist") is None
    assert studio_release(raw_release("a", "Live!"), "artist") is None
    assert (
        studio_release(raw_release("a") | {"album_type": "compilation"}, "artist")
        is None
    )
    assert studio_release(raw_release("a"), "artist") is not None
