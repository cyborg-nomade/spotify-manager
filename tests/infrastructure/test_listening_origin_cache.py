"""Persistent country metadata, bounded versions and corrupt-evidence rejection."""

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from pathlib import Path

import pytest

from spotify_manager.application.listening_origin_ports import OriginCacheError
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.infrastructure.listening import origin_cache
from spotify_manager.infrastructure.listening.origin_cache import ArtistOriginCache
from spotify_manager.infrastructure.listening.origin_cache import decode_origin_metadata
from tests.support.listening_origins import origin_metadata


def test_restart_generations_and_oldest_eviction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only complete immutable observations survive restarts and bounded eviction."""
    monkeypatch.setattr(origin_cache, "MAX_CACHED_ARTISTS", 2)
    cache = ArtistOriginCache(tmp_path)
    empty = cache.current()
    cache.write(origin_metadata("Old", fetched_at="2020-01-01T00:00:00+00:00"))
    first = cache.current()
    assert cache.acquire(empty.snapshot) is empty
    assert ArtistOriginCache(tmp_path).current().entries == first.entries
    cache.write(origin_metadata())
    with pytest.raises(ListeningVersionError):
        cache.acquire(empty.snapshot)
    assert cache.acquire(first.snapshot) is first
    cache.write(origin_metadata("New", fetched_at="2026-11-22T00:00:00+00:00"))
    assert {item.artist_name for item in cache.current().entries} == {"Alpha", "New"}
    assert (tmp_path / "artist-origins-v1.sqlite").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "field,value",
    [
        ("artist_key", "wrong"),
        ("artist_name", None),
        ("state", "guessed"),
        ("candidate_count", True),
        ("candidate_count", 2),
        ("candidate_count", 101),
        ("candidates", {}),
        ("candidates", [None]),
        ("fetched_at", "2026-01-01"),
    ],
)
def test_invalid_metadata_never_reaches_the_cache(field: str, value: object) -> None:
    """Typed outcomes, identities, complete counts and aware dates are required."""
    raw = asdict(origin_metadata())
    raw[field] = value
    with pytest.raises(ValueError):
        decode_origin_metadata(json.dumps(raw))


@pytest.mark.parametrize(
    "field,value",
    [
        ("mbid", "bad"),
        ("mbid", "AAAA0000-0000-0000-0000-000000000000"),
        ("name", "Someone else"),
        ("area", None),
        ("countries", {}),
        ("countries", ["bad"]),
        ("countries", ["US", "BR"]),
        ("countries", ["BR", "BR"]),
        ("countries", [None]),
    ],
)
def test_invalid_candidate_rows_never_invent_country_evidence(
    field: str, value: object
) -> None:
    """Candidate identity and original place fields are checked on every reload."""
    raw = asdict(origin_metadata())
    candidate = asdict(origin_metadata().candidates[0])
    candidate[field] = value
    raw["candidates"] = [candidate]
    with pytest.raises(ValueError):
        decode_origin_metadata(json.dumps(raw))


def test_lookup_outcomes_round_trip_and_duplicate_candidates_are_rejected() -> None:
    """All completed outcomes survive without silently becoming unique matches."""
    for metadata in (
        origin_metadata(state="unmatched", count=0),
        origin_metadata(state="ambiguous", count=2),
        origin_metadata(state="incomplete", count=0),
    ):
        assert decode_origin_metadata(json.dumps(asdict(metadata))) == metadata
    raw = asdict(origin_metadata(state="ambiguous", count=2))
    raw["candidates"] = [asdict(origin_metadata().candidates[0])] * 2
    with pytest.raises(ValueError):
        decode_origin_metadata(json.dumps(raw))
    with pytest.raises(ValueError):
        decode_origin_metadata("[]")


def test_storage_failure_preserves_complete_memory_and_corruption_is_visible(
    tmp_path: Path,
) -> None:
    """A bad derived cache never blocks canonical history or publishes partial rows."""
    cache = ArtistOriginCache(tmp_path)
    cache.write(origin_metadata())
    before = cache.current()
    with (
        closing(sqlite3.connect(tmp_path / "artist-origins-v1.sqlite")) as connection,
        connection,
    ):
        connection.execute("DROP TABLE observations")
    with pytest.raises(OriginCacheError):
        cache.write(origin_metadata("Beta"))
    assert cache.current() is before
    (tmp_path / "artist-origins-v1.sqlite").write_bytes(b"broken")
    broken = ArtistOriginCache(tmp_path)
    assert broken.current().message and not broken.current().entries
    with pytest.raises(OriginCacheError):
        broken.write(origin_metadata())
