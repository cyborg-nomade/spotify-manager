"""Protect tolerant Palace state, manual references and exact atomic JSON bytes."""

import json
from datetime import UTC
from datetime import datetime
from pathlib import Path
from typing import TextIO

import pytest

from spotify_manager.application.palace_values import PalaceOfMemoryConfigError
from spotify_manager.application.palace_values import PalaceOfMemoryStateError
from spotify_manager.infrastructure.palace_cursor import cursor_record
from spotify_manager.infrastructure.palace_cursor import load_state
from spotify_manager.infrastructure.palace_cursor import resolve_start
from spotify_manager.infrastructure.palace_cursor import save_state
from spotify_manager.infrastructure.palace_cursor import validate_state
from spotify_manager.models.your_library import YourLibraryAlbum


ALBUMS = (
    YourLibraryAlbum(artist="Artist", album="Release", uri="spotify:album:first"),
    YourLibraryAlbum(artist="Other", album="Second", uri="spotify:album:second"),
)


@pytest.mark.parametrize("index", [0, 1, True, False])
def test_palace_cursor_retains_original_bool_and_unknown_fields(index: int) -> None:
    """Keep the original complete mutable dictionary and integer/bool tolerance.

    Args:
        index: Original tolerated fallback value.
    """
    record: dict[str, object] = {
        "next_alphabetical_index": index,
        "unknown": [1, "Björk"],
    }
    assert validate_state(record) is record
    assert validate_state({}) == {}


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        "cursor",
        {"next_alphabetical_index": -1},
        {"next_alphabetical_index": 0.0},
        {"next_alphabetical_index": "1"},
    ],
)
def test_palace_cursor_rejects_original_root_and_index_errors(raw: object) -> None:
    """Retain original shape and numeric guard errors.

    Args:
        raw: Original unusable decoded namespace.
    """
    with pytest.raises(PalaceOfMemoryStateError):
        validate_state(raw)


def _fail_open(path: Path, *args: object, **options: object) -> TextIO:
    raise OSError("open failed")


def _fail_replace(path: Path, target: Path | str) -> Path:
    raise OSError("replacement failed")


def test_palace_cursor_load_preserves_missing_and_complete_records(
    tmp_path: Path,
) -> None:
    """Keep original missing defaults and full validated JSON dictionaries.

    Args:
        tmp_path: Isolated original cursor location.
    """
    path = tmp_path / "cursor.json"
    assert load_state(path) == {}
    path.write_text('{"next_alphabetical_index": true, "unknown": [1]}')
    assert load_state(path) == {"next_alphabetical_index": True, "unknown": [1]}


@pytest.mark.parametrize(
    "text,fragment", [("{bad", "line 1, column 2"), ("[]", "Palace state is invalid")]
)
def test_palace_cursor_load_preserves_original_error_context(
    tmp_path: Path,
    text: str,
    fragment: str,
) -> None:
    """Retain original malformed JSON locations and generic validation translation.

    Args:
        tmp_path: Isolated original cursor location.
        text: Original malformed file contents.
        fragment: Original translated error fragment.
    """
    path = tmp_path / "cursor.json"
    path.write_text(text)
    with pytest.raises(PalaceOfMemoryStateError, match=fragment) as error:
        load_state(path)
    assert error.value.__cause__ is not None
    assert str(path) in str(error.value)


def test_palace_cursor_load_preserves_original_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain original narrowed read-error translation.

    Args:
        tmp_path: Isolated original cursor location.
        monkeypatch: Original configured I/O failure boundary.
    """
    path = tmp_path / "cursor.json"
    path.write_text("{}")
    monkeypatch.setattr(Path, "open", _fail_open)
    with pytest.raises(PalaceOfMemoryStateError, match="Could not read Palace state"):
        load_state(path)


def test_palace_cursor_save_retains_unicode_fields_and_atomic_bytes(
    tmp_path: Path,
) -> None:
    """Preserve original complete replacement bytes and remove the accepted temp file.

    Args:
        tmp_path: Isolated original cursor location.
    """
    path = tmp_path / "nested/cursor.json"
    payload: dict[str, object] = {"next_alphabetical_index": True, "unknown": "Björk"}
    save_state(payload, path)
    assert path.read_text() == json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    assert not path.with_suffix(".json.tmp").exists()


def test_palace_cursor_save_preserves_failed_replacement_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain the original failed temp file instead of silently cleaning it up.

    Args:
        tmp_path: Isolated original cursor location.
        monkeypatch: Original configured replacement failure boundary.
    """
    path = tmp_path / "cursor.json"
    monkeypatch.setattr(Path, "replace", _fail_replace)
    with pytest.raises(PalaceOfMemoryStateError, match="Could not save Palace state"):
        save_state({}, path)
    assert path.with_suffix(".json.tmp").read_text() == "{}\n"
    assert not path.exists()


def test_palace_cursor_record_retains_independent_clock_and_last_album_fields() -> None:
    """Keep the original replacement shape and supplied write timestamp."""
    now = datetime(2026, 8, 8, tzinfo=UTC)
    assert cursor_record(1, ALBUMS[0], now) == {
        "updated_at": now.isoformat(),
        "next_alphabetical_index": 1,
        "last_alphabetical_album_id": "first",
        "last_alphabetical_artist": "Artist",
        "last_alphabetical_album": "Release",
    }


@pytest.mark.parametrize(
    "reference,index",
    [
        ("1", 0),
        ("٢", 1),
        ("first", 0),
        ("spotify:album:second?extra", 1),
        ("https://open.spotify.com/album/second/?x", 1),
        (" release ", 0),
        ("OTHER - SECOND", 1),
    ],
)
def test_palace_manual_reference_preserves_original_supported_forms(
    reference: str,
    index: int,
) -> None:
    """Retain original whitespace, case, Unicode decimal and reference parsing.

    Args:
        reference: Original supported manual value.
        index: Original expected zero-based position.
    """
    assert resolve_start(ALBUMS, reference) == index


@pytest.mark.parametrize(
    "reference,fragment",
    [
        (" ", "cannot be empty"),
        ("0", "between 1 and 2"),
        ("3", "between 1 and 2"),
        ("absent", "was not found"),
    ],
)
def test_palace_manual_reference_retains_original_invalid_errors(
    reference: str,
    fragment: str,
) -> None:
    """Keep original empty, numeric-boundary and unfound reference errors.

    Args:
        reference: Original unusable manual value.
        fragment: Original expected error fragment.
    """
    with pytest.raises(PalaceOfMemoryConfigError, match=fragment):
        resolve_start(ALBUMS, reference)


def test_palace_manual_label_ambiguity_preserves_five_examples() -> None:
    """Retain original ambiguity wording and the five-example display cap."""
    albums = []
    for index in range(6):
        albums.append(
            YourLibraryAlbum(
                artist=f"Artist {index}", album="Common", uri=f"spotify:album:{index}"
            )
        )
    with pytest.raises(PalaceOfMemoryConfigError, match="ambiguous") as error:
        resolve_start(tuple(albums), "Common")
    assert "Artist 4 - Common (4)" in str(error.value)
    assert "Artist 5 - Common (5)" not in str(error.value)
