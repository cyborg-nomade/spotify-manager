"""Persistent metadata provenance, immutable versions and safe failure behavior."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import pytest

from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.application.listening_tag_ports import TagCacheError
from spotify_manager.infrastructure.listening import tag_cache
from spotify_manager.infrastructure.listening.tag_cache import ArtistTagCache
from spotify_manager.infrastructure.listening.tag_cache import decode_tag_metadata
from tests.support.listening_tags import tag_metadata


def test_completed_metadata_survives_restart_and_previous_generations_are_pinned(
    tmp_path: Path,
) -> None:
    """Disk persistence and two complete generations are independent of history."""
    cache = ArtistTagCache(tmp_path)
    empty = cache.current()
    cache.write(tag_metadata())
    first = cache.current()
    assert cache.acquire(empty.snapshot) is empty
    restored = ArtistTagCache(tmp_path).current()
    assert restored.snapshot == first.snapshot and restored.entries == first.entries
    cache.write(tag_metadata("Beta"))
    assert first.entries[0].artist_name == "Alpha"
    with pytest.raises(ListeningVersionError):
        cache.acquire(empty.snapshot)
    assert cache.acquire(first.snapshot) is first
    assert (tmp_path / "artist-tags-v1.sqlite").stat().st_mode & 0o777 == 0o600


def test_cache_bound_evicts_oldest_observations_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Derived cache limits bound memory without mutating canonical data."""
    monkeypatch.setattr(tag_cache, "MAX_CACHED_ARTISTS", 2)
    cache = ArtistTagCache(tmp_path)
    cache.write(tag_metadata("Old", fetched_at="2020-01-01T00:00:00+00:00"))
    cache.write(tag_metadata("Recent"))
    cache.write(tag_metadata("Newest", fetched_at="2026-11-22T00:00:00+00:00"))
    assert {item.artist_name for item in cache.current().entries} == {
        "Recent",
        "Newest",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("artist_key", "wrong"),
        ("state", "guessed"),
        ("tags", {}),
        ("tags", [{"key": "wrong", "name": "Rock"}]),
        ("fetched_at", "2026-01-01"),
        ("resolved_name", "Someone else"),
        ("artist_name", None),
    ],
)
def test_corrupt_cached_observations_never_become_asserted_metadata(
    field: str, value: object
) -> None:
    """Every exposed cache row preserves its identity and dated provenance."""
    document = asdict(tag_metadata())
    document[field] = value
    with pytest.raises(ValueError):
        decode_tag_metadata(json.dumps(document))


def test_failed_write_retains_the_last_complete_cache(tmp_path: Path) -> None:
    """A storage outage cannot erase already available derived evidence."""
    cache = ArtistTagCache(tmp_path)
    cache.write(tag_metadata())
    before = cache.current()
    with (
        closing(sqlite3.connect(tmp_path / "artist-tags-v1.sqlite")) as connection,
        connection,
    ):
        connection.execute("DROP TABLE observations")
    with pytest.raises(TagCacheError):
        cache.write(tag_metadata("Beta"))
    assert cache.current() is before


def test_invalid_cache_is_visible_and_does_not_block_history_startup(
    tmp_path: Path,
) -> None:
    """Derived cache corruption degrades to explicitly unavailable metadata."""
    (tmp_path / "artist-tags-v1.sqlite").write_bytes(b"not a database")
    cache = ArtistTagCache(tmp_path)
    assert cache.current().entries == ()
    assert "unavailable" in cache.current().message
    with pytest.raises(TagCacheError):
        cache.write(tag_metadata())


@pytest.mark.parametrize(
    "document",
    [
        "[]",
        json.dumps({**asdict(tag_metadata()), "tags": [None]}),
        json.dumps({**asdict(tag_metadata()), "state": "empty"}),
    ],
)
def test_invalid_cache_root_rows_and_availability_are_rejected(document: str) -> None:
    """Malformed derived evidence cannot silently become available tags."""
    with pytest.raises(ValueError):
        decode_tag_metadata(document)
