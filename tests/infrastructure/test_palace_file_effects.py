"""Protect original Palace file errors, audit bytes and pre-replacement backups."""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import TextIO

import pytest

from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.application.palace_values import PalaceOfMemoryStateError
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.infrastructure.palace_files import append_audit
from spotify_manager.infrastructure.palace_files import load_saved_albums
from spotify_manager.infrastructure.palace_files import replace_saved_albums
from spotify_manager.models.your_library import YourLibraryAlbum
from tests.support.queue_neighbors import NOW


ALBUM = YourLibraryAlbum(artist="Björk", album="Debut", uri="spotify:album:one")


def _fail_open(path: Path, *args: object, **options: object) -> TextIO:
    raise OSError("open failed")


def _fail_copy(source: Path, destination: Path) -> str:
    raise OSError("backup failed")


def _write(path: Path, albums: tuple[YourLibraryAlbum, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            [album.model_dump() for album in albums], ensure_ascii=False, indent=2
        )
        + "\n"
    )


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("{bad", "line 1, column 2"),
        ("{}", "must be a JSON list"),
        ("[{}]", "Saved albums are invalid"),
        ("[]", "At least 5"),
    ],
)
def test_palace_mirror_load_retains_original_root_and_model_errors(
    tmp_path: Path,
    text: str,
    fragment: str,
) -> None:
    """Keep original parsing locations, model validation and minimum population errors.

    Args:
        tmp_path: Isolated canonical mirror location.
        text: Original unusable file contents.
        fragment: Original expected error fragment.
    """
    path = tmp_path / "albums.json"
    path.write_text(text)
    with pytest.raises(PalaceOfMemoryDataError, match=fragment):
        load_saved_albums(path)


def test_palace_mirror_load_retains_original_read_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain original narrowed file-read error translation.

    Args:
        tmp_path: Isolated canonical mirror location.
        monkeypatch: Original configured file failure.
    """
    monkeypatch.setattr(Path, "open", _fail_open)
    with pytest.raises(PalaceOfMemoryDataError, match="Could not read saved albums"):
        load_saved_albums(tmp_path / "albums.json")


def test_palace_preflight_audit_retains_original_utf8_dates_and_newline(
    tmp_path: Path,
) -> None:
    """Keep original JSON field order, date text and Unicode serialization.

    Args:
        tmp_path: Isolated preflight audit location.
    """
    path = tmp_path / "audit.jsonl"
    refresh = SavedAlbumRefresh(NOW, 5, 6, 1, 0, 2, True, "Björk")
    append_audit(path, refresh, "saved-album refresh log")
    record = {
        "checked_at": NOW.isoformat(),
        "previous": 5,
        "current": 6,
        "added": 1,
        "removed": 0,
        "skipped": 2,
        "persisted": True,
        "backup_path": "Björk",
    }
    assert path.read_text() == json.dumps(record, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("label", ["saved-album refresh log", "Palace log"])
def test_palace_audit_retains_original_path_error_labels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
) -> None:
    """Keep distinct original preflight and completion write-error labels.

    Args:
        tmp_path: Isolated audit location.
        monkeypatch: Original configured append failure.
        label: Original audit-specific path label.
    """
    monkeypatch.setattr(Path, "open", _fail_open)
    refresh = SavedAlbumRefresh(NOW, 5, 5, 0, 0, 0, False, None)
    with pytest.raises(PalaceOfMemoryStateError, match=f"Could not write {label}"):
        append_audit(tmp_path / "audit.jsonl", refresh, label)


def _clock() -> datetime:
    return NOW


def test_palace_mirror_backup_retains_original_bytes_before_unicode_replacement(
    tmp_path: Path,
) -> None:
    """Keep the original source bytes and fixed timestamped backup name.

    Args:
        tmp_path: Isolated canonical mirror and backup locations.
    """
    path = tmp_path / "albums.json"
    path.write_text("original bytes")
    backup = replace_saved_albums(path, tmp_path / "backups", (ALBUM,), _clock, _write)
    assert backup is not None
    assert Path(backup).read_text() == "original bytes"
    assert (
        Path(backup).name == NOW.strftime("%Y%m%dT%H%M%S%fZ") + "-albums_total_new.json"
    )
    assert json.loads(path.read_text()) == [ALBUM.model_dump()]
    assert (
        replace_saved_albums(
            tmp_path / "new.json", tmp_path / "backups", (ALBUM,), _clock, _write
        )
        is None
    )


def test_palace_mirror_backup_failure_preserves_original_before_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain original bytes and narrowed backup-error translation.

    Args:
        tmp_path: Isolated canonical mirror and backup locations.
        monkeypatch: Original configured backup failure boundary.
    """
    path = tmp_path / "albums.json"
    path.write_text("original bytes")
    monkeypatch.setattr(shutil, "copy2", _fail_copy)
    with pytest.raises(PalaceOfMemoryStateError, match="Could not publish refreshed"):
        replace_saved_albums(path, tmp_path / "backups", (ALBUM,), _clock, _write)
    assert path.read_text() == "original bytes"
