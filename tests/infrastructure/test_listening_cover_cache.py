"""Atomic artwork, immutable generations and visible corrupt-cache errors."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from dataclasses import replace
from pathlib import Path

import pytest

from spotify_manager.application.listening_cover_ports import CoverCacheError
from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.application.listening_covers import get_quilt_image
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.infrastructure.listening import cover_cache
from spotify_manager.infrastructure.listening.cover_cache import AlbumCoverCache
from spotify_manager.infrastructure.listening.cover_codec import decode_cover_image
from spotify_manager.infrastructure.listening.cover_codec import decode_cover_metadata
from tests.support.listening_covers import cover_result


def test_restart_pins_images_and_metadata_together_and_evicts_oldest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An acquired generation retains its bytes after later database eviction.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
        monkeypatch: Scoped replacements for timing and concrete integration boundaries.
    """
    monkeypatch.setattr(cover_cache, "MAX_CACHED_ALBUMS", 2)
    cache = AlbumCoverCache(tmp_path)
    empty = cache.current()
    old = cover_result("Old", fetched_at="2020-01-01T00:00:00+00:00")
    cache.write(old)
    first = cache.current()
    restored = AlbumCoverCache(tmp_path).current()
    assert restored.snapshot == first.snapshot and restored.entries == first.entries
    assert (
        old.image is not None
        and get_quilt_image(restored, old.metadata.album_key) == old.image.content
    )
    cache.write(cover_result())
    with pytest.raises(ListeningVersionError):
        cache.acquire(empty.snapshot)
    cache.write(cover_result("New", fetched_at="2026-11-23T00:00:00+00:00"))
    assert {item.album_name for item in cache.current().entries} == {"Record", "New"}
    assert get_quilt_image(first, old.metadata.album_key) == old.image.content
    assert (tmp_path / "album-covers-v1.sqlite").stat().st_mode & 0o777 == 0o600
    assert get_quilt_image(cache.current(), "0" * 64) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("album_key", "wrong"),
        ("album_name", None),
        ("album_name", ""),
        ("album_name", "x" * 1001),
        ("state", "guessed"),
        ("state", "no_cover"),
        ("candidate_count", True),
        ("candidate_count", 101),
        ("candidate_count", 2),
        ("fetched_at", "2026-01-01"),
        ("candidates", {}),
        ("candidates", [None]),
    ],
)
def test_invalid_documents_never_claim_available_artwork(
    field: str, value: object
) -> None:
    """Persisted fields stay strict, bounded, name-checked and time-zone aware.

    Args:
        field: Persisted field deliberately replaced to verify strict validation.
        value: Controlled external value used to verify acceptance or rejection.
    """
    raw = asdict(cover_result().metadata)
    raw[field] = value
    with pytest.raises((ValueError, CoverSourceError)):
        decode_cover_metadata(json.dumps(raw))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mbid", "bad"),
        ("title", "Different title"),
        ("artist", "Different artist"),
        ("description", "x" * 1001),
    ],
)
def test_candidate_identity_names_and_text_remain_corroborated(
    field: str, value: object
) -> None:
    """Candidate identity names and text remain corroborated.

    Args:
        field: Persisted field deliberately replaced to verify strict validation.
        value: Controlled external value used to verify acceptance or rejection.
    """
    raw = asdict(cover_result().metadata)
    candidate = asdict(cover_result().metadata.candidates[0])
    candidate[field] = value
    raw["candidates"] = [candidate]
    with pytest.raises((ValueError, CoverSourceError)):
        decode_cover_metadata(json.dumps(raw))


def test_all_outcomes_roundtrip_and_duplicate_candidates_are_rejected(
    tmp_path: Path,
) -> None:
    """Unavailable art is a valid complete observation, never invented image bytes.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
    """
    cache = AlbumCoverCache(tmp_path)
    for result in (
        cover_result("No cover", state="no_cover"),
        cover_result("No match", state="unmatched", count=0),
        cover_result("Many", state="ambiguous", count=2),
        cover_result("Partial", state="incomplete", count=0),
    ):
        cache.write(result)
        assert result.metadata in cache.current().entries
        assert get_quilt_image(cache.current(), result.metadata.album_key) is None
    raw = asdict(cover_result(state="ambiguous", count=2).metadata)
    candidate = asdict(cover_result().metadata.candidates[0])
    raw["candidates"] = [candidate, candidate]
    with pytest.raises(ValueError):
        decode_cover_metadata(json.dumps(raw))
    with pytest.raises(ValueError):
        decode_cover_metadata("x" * 32769)


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_mbid", "bad"),
        ("image_id", "/bad"),
        ("sha256", "0" * 64),
        ("width", 1),
        ("height", 1),
    ],
)
def test_image_provenance_hash_and_dimensions_must_agree(
    field: str, value: object
) -> None:
    """Image provenance hash and dimensions must agree.

    Args:
        field: Persisted field deliberately replaced to verify strict validation.
        value: Controlled external value used to verify acceptance or rejection.
    """
    result = cover_result()
    raw = asdict(result.metadata)
    assert result.metadata.artwork is not None and result.image is not None
    artwork = asdict(result.metadata.artwork)
    artwork[field] = value
    raw["artwork"] = artwork
    metadata = decode_cover_metadata(json.dumps(raw))
    with pytest.raises((ValueError, CoverSourceError)):
        decode_cover_image(metadata, result.image.content)


def test_missing_extra_and_conflicting_image_bytes_are_rejected(tmp_path: Path) -> None:
    """Missing extra and conflicting image bytes are rejected.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
    """
    result = cover_result()
    assert result.image is not None
    with pytest.raises(ValueError):
        decode_cover_image(result.metadata, None)
    with pytest.raises(ValueError):
        decode_cover_image(
            cover_result(state="no_cover").metadata, result.image.content
        )
    cache = AlbumCoverCache(tmp_path)
    wrong = replace(result.image, sha256="0" * 64)
    with pytest.raises(CoverCacheError):
        cache.write(replace(result, image=wrong))
    assert not cache.current().entries


def test_storage_failure_and_corruption_preserve_complete_memory(
    tmp_path: Path,
) -> None:
    """Storage failure and corruption preserve complete memory.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
    """
    cache = AlbumCoverCache(tmp_path)
    cache.write(cover_result())
    before = cache.current()
    with (
        closing(sqlite3.connect(tmp_path / "album-covers-v1.sqlite")) as connection,
        connection,
    ):
        connection.execute("DROP TABLE observations")
    with pytest.raises(CoverCacheError):
        cache.write(cover_result("Next"))
    assert cache.current() is before
    (tmp_path / "album-covers-v1.sqlite").write_bytes(b"broken")
    broken = AlbumCoverCache(tmp_path)
    assert broken.current().message and not broken.current().entries
    with pytest.raises(CoverCacheError):
        broken.write(cover_result())


def test_oversized_persisted_row_count_is_visible_not_silently_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oversized persisted row count is visible not silently partial.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
        monkeypatch: Scoped replacements for timing and concrete integration boundaries.
    """
    cache = AlbumCoverCache(tmp_path)
    cache.write(cover_result("One"))
    cache.write(cover_result("Two"))
    monkeypatch.setattr(cover_cache, "MAX_CACHED_ALBUMS", 1)
    assert AlbumCoverCache(tmp_path).current().message


def test_incomplete_candidate_count_and_missing_image_never_expose_other_bytes() -> (
    None
):
    """Partial cached evidence cannot borrow a different album's validated image."""
    raw = asdict(cover_result(state="incomplete", count=2).metadata)
    raw["candidates"] = raw["candidates"][:1]
    with pytest.raises(ValueError):
        decode_cover_metadata(json.dumps(raw))
    selected, other = cover_result(), cover_result("Other", color="#112233")
    assert other.image is not None
    catalog = CoverCatalog("c1-test", (selected.metadata,), (other.image,))
    assert get_quilt_image(catalog, selected.metadata.album_key) is None
