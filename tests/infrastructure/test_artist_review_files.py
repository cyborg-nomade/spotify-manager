"""Verify original review file bytes, publication order and atomic failure effects."""

import json
from dataclasses import dataclass
from dataclasses import field
from functools import partial
from pathlib import Path

import pytest

from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.infrastructure import artist_review_files as files
from spotify_manager.models.your_library import YourLibraryArtist


@dataclass
class Publications:
    """Observe original sorted mirror publication after its durable replacement.

    Args:
        calls: Ordered original publication observations.
    """

    calls: list[tuple[str, object]] = field(default_factory=list)

    def write(self, path: Path, value: object) -> None:
        """Observe and accept original complete JSON replacement.

        Args:
            path: Original destination.
            value: Original complete sorted model list.
        """
        self.calls.append(("write", value))
        files.write_json_atomic(path, value)

    def publish(self, path: Path) -> None:
        """Observe the accepted original mirror before publishing it.

        Args:
            path: Original accepted canonical file.
        """
        self.calls.append(("publish", json.loads(path.read_text())))


def _read_value(value: object, path: Path, default: object) -> object:
    return value


def _unexpected_read(path: Path, default: object) -> object:
    raise AssertionError("Original refresh must skip the cache read")


def _failed_replace(source: Path, target: Path | str) -> Path:
    raise OSError("original replacement failed")


def test_review_json_missing_default_and_invalid_json_error(tmp_path: Path) -> None:
    """Retain same fallback identity, exact error and original decoding cause.

    Args:
        tmp_path: Isolated local boundary.
    """
    path = tmp_path / "missing.json"
    default: dict[str, object] = {"unchanged": True}
    assert files.load_json(path, default) is default
    path.write_text("torn{")
    with pytest.raises(ArtistReviewError, match=f"Invalid JSON in {path}") as error:
        files.load_json(path, default)
    assert isinstance(error.value.__cause__, json.JSONDecodeError)


def test_review_atomic_json_and_audit_preserve_original_utf8_bytes(
    tmp_path: Path,
) -> None:
    """Retain original indent, non-ASCII encoding, newline and no empty log write.

    Args:
        tmp_path: Isolated original file locations.
    """
    value: dict[str, object] = {"artist": "Beyoncé", "pending": []}
    path = tmp_path / "nested" / "cache.json"
    files.write_json_atomic(path, value)
    assert path.read_text() == json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    assert files.load_json(path, {}) == value
    assert not path.with_suffix(".json.tmp").exists()
    log = tmp_path / "log" / "events.jsonl"
    files.append_events(log, [])
    assert not log.exists()
    files.append_events(log, [value, {"next": True}])
    assert (
        log.read_text() == json.dumps(value, ensure_ascii=False) + '\n{"next": true}\n'
    )


def test_failed_review_replacement_retains_original_destination_and_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain original temporary bytes when replacement fails after a complete write.

    Args:
        tmp_path: Isolated original atomic destination.
        monkeypatch: Narrow replacement failure injection.
    """
    path = tmp_path / "state.json"
    path.write_text("original\n")
    monkeypatch.setattr(Path, "replace", _failed_replace)
    with pytest.raises(OSError, match="original replacement failed"):
        files.write_json_atomic(path, {"new": True})
    assert path.read_text() == "original\n"
    assert path.with_suffix(".json.tmp").read_text() == '{\n  "new": true\n}\n'


def test_review_model_list_guard_and_complete_model_validation(tmp_path: Path) -> None:
    """Retain missing-list defaults and exact non-list guards at the caller seam.

    Args:
        tmp_path: Isolated original mirror location.
    """
    path = tmp_path / "artists.json"
    assert files.load_models(path, YourLibraryArtist, files.load_json) == []
    path.write_text("{}")
    with pytest.raises(ArtistReviewError, match=f"Expected a JSON list in {path}"):
        files.load_models(path, YourLibraryArtist, files.load_json)
    path.write_text('[{"name": "A", "uri": "spotify:artist:a"}]')
    assert files.load_models(path, YourLibraryArtist, files.load_json) == [
        YourLibraryArtist(name="A", uri="spotify:artist:a")
    ]


def test_review_artist_publication_sorts_same_list_after_successful_write(
    tmp_path: Path,
) -> None:
    """Retain caller-list sorting and durable write before canonical publication.

    Args:
        tmp_path: Isolated canonical artist mirror.
    """
    path = tmp_path / "artists.json"
    artists = [
        YourLibraryArtist(name="B", uri="spotify:artist:b"),
        YourLibraryArtist(name="A", uri="spotify:artist:a"),
    ]
    effects = Publications()
    files.save_artists(path, artists, effects.write, effects.publish)
    assert [artist.name for artist in artists] == ["A", "B"]
    expected = [artist.model_dump() for artist in artists]
    assert effects.calls == [("write", expected), ("publish", expected)]


def test_review_cache_keeps_original_refresh_and_shallow_root_semantics(
    tmp_path: Path,
) -> None:
    """Retain refresh-before-read, original error and same unvalidated object.

    Args:
        tmp_path: Isolated complete metadata cache.
    """
    path = tmp_path / "cache.json"
    assert files.load_cache(path, True, _unexpected_read) == {}
    with pytest.raises(ArtistReviewError, match=f"Expected a JSON object in {path}"):
        files.load_cache(path, False, partial(_read_value, []))
    raw: dict[str, object] = {"artist": "unvalidated", "retained": True}
    assert files.load_cache(path, False, partial(_read_value, raw)) is raw
