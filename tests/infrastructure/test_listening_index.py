"""Published-only indexing, atomic replacement, and exact SQL/calendar reads."""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path
from threading import Event
from threading import Thread

import pytest

from spotify_manager.application.listening_ports import ListeningNotReadyError
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankingOptions
from spotify_manager.domain.listening_values import RecordOptions
from spotify_manager.infrastructure.listening.build import _source_row
from spotify_manager.infrastructure.listening.build import _text
from spotify_manager.infrastructure.listening.build import build_listening_index
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening import sample_history
from tests.support.listening import scrobble


QUERY = ListeningQuery(date(2024, 1, 1), date(2024, 7, 1), "UTC")


@pytest.fixture
async def source(tmp_path: Path) -> AsyncIterator[ListeningFixture]:
    fixture = listening_fixture(tmp_path)
    try:
        yield fixture
    finally:
        await fixture.runtime.close()


async def ready(fixture: ListeningFixture) -> str:
    fixture.runtime.status(refresh=True)
    task = fixture.runtime._task
    assert task is not None
    await task
    status = fixture.runtime.status()
    assert status.metadata is not None, status
    return status.metadata.snapshot


async def test_only_published_rows_are_indexed_and_unchanged_source_is_reused(
    source: ListeningFixture,
) -> None:
    source.publish(sample_history())
    revision = source.service.snapshot().revision
    source.source.write_text("a sync is editing the working copy")
    token = await ready(source)
    with source.runtime.acquire(token) as index:
        assert index.counts(QUERY).scrobbles == 7
        original = index
        assert index.metadata.source_bytes > 0
    assert await ready(source) == token
    with source.runtime.acquire(token) as index:
        assert index is original
    assert source.service.snapshot().revision == revision
    assert source.source.read_text() == "a sync is editing the working copy"
    assert not list(source.runtime._root.glob("scrobble-download-*"))


async def test_same_row_count_correction_invalidates_and_old_reader_survives(
    source: ListeningFixture,
) -> None:
    source.publish(sample_history())
    old = await ready(source)
    with source.runtime.acquire(old) as reader:
        original_path = reader.path
        for artist in ("Changed", "Changed again", "Third correction"):
            source.publish([scrobble("2024-01-01T12:00:00", artist)] * 7)
            current = await ready(source)
            assert current != old
        assert original_path.exists()
        assert reader.counts(QUERY).artists == 3
    assert not original_path.exists()
    with pytest.raises(ListeningVersionError):
        with source.runtime.acquire(old):
            pass
    with source.runtime.acquire(current) as reader:
        assert reader.counts(QUERY).artists == 1


async def test_missing_and_corrupt_publication_are_visible_and_recoverable(
    source: ListeningFixture,
) -> None:
    with pytest.raises(ListeningNotReadyError):
        with source.runtime.acquire("v1-" + "0" * 64):
            pass
    source.runtime.status()
    assert source.runtime._task is not None
    await source.runtime._task
    assert source.runtime.status().state == "missing"
    source.publish(sample_history())
    token = await ready(source)
    source.publish([{"date": "invalid", "artist": "A", "track": "T"}])
    await ready(source)
    assert source.runtime.status().state == "stale"
    with source.runtime.acquire(token) as index:
        assert index.counts(QUERY).scrobbles == 7
    assert not list(source.runtime._root.glob("*.building"))
    assert not list(source.runtime._root.glob("scrobble-download-*"))
    source.publish(sample_history())
    assert await ready(source) == token
    assert source.runtime.status().state == "ready"


async def test_empty_history_and_deleted_cache_rebuild(
    source: ListeningFixture,
) -> None:
    source.publish([])
    token = await ready(source)
    with source.runtime.acquire(token) as index:
        assert index.metadata.scrobbles == 0
        assert index.metadata.first_ms is None
        assert index.counts(QUERY).active_days == 0
        index.path.unlink()
    assert await ready(source) == token
    with source.runtime.acquire(token) as index:
        assert index.path.exists()


async def test_search_identity_order_pagination_and_original_names(
    source: ListeningFixture,
) -> None:
    source.publish(sample_history())
    token = await ready(source)
    with source.runtime.acquire(token) as index:
        search = index.rankings(QUERY, RankingOptions(search="BÉTA"))
        assert search.total == 1 and search.items[0].name == "Béta"
        assert search.items[0].share == pytest.approx(1 / 7)
        assert index.rankings(QUERY, RankingOptions(search="' OR 1=1 --")).total == 0
        page = index.rankings(QUERY, RankingOptions(page=2, limit=1, order="name"))
        assert page.total == 3 and len(page.items) == 1
        records = index.records(QUERY, RecordOptions(page=2, limit=2))
        assert len(records.items) == 2 and records.total == 7
        original = index.records(QUERY, RecordOptions(limit=100))
        assert original.items[4].artist == "ALPHA"
        assert original.items[-2].ordinal < original.items[-1].ordinal
        albums = index.rankings(QUERY, RankingOptions(kind="album"))
        assert albums.total == 3


async def test_rhythm_timezone_and_artist_filters_are_exact(
    source: ListeningFixture,
) -> None:
    source.publish(sample_history())
    token = await ready(source)
    with source.runtime.acquire(token) as index:
        alpha = listening_identity(("alpha",))
        monday = ListeningQuery(QUERY.start, QUERY.end, "UTC", alpha, 0, 12)
        assert index.counts(monday).scrobbles == 4
        assert len(index.artist_plays(monday)) == 4
        assert not index.artist_plays(
            ListeningQuery(QUERY.start, QUERY.end, "UTC", hour=13)
        )
        assert (
            index.counts(
                ListeningQuery(QUERY.start, QUERY.end, "UTC", hour=13)
            ).scrobbles
            == 0
        )
        for zone in (
            "Europe/Berlin",
            "America/Sao_Paulo",
            "Asia/Tokyo",
            "Australia/Sydney",
            "UTC",
        ):
            assert (
                index.counts(ListeningQuery(QUERY.start, QUERY.end, zone)).scrobbles
                >= 6
            )
        assert len(index._zones) == 4
        assert len(list(index.path.parent.glob("*.zone"))) == 4


@pytest.mark.parametrize(
    "row",
    [
        None,
        {"date": True},
        {"date": -1},
        {"date": 4102444800000},
        {"date": 1, "artist": "A", "track": []},
    ],
)
def test_invalid_rows_cannot_be_silently_skipped(row: object) -> None:
    with pytest.raises(ValueError):
        _source_row(row, 0)


def test_invalid_text_and_container_fail_explicitly(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _text({"album": ["bad"]}, "album")
    with pytest.raises(ValueError):
        _text({"album": 0}, "album")
    source = listening_fixture(tmp_path)
    source.publish(sample_history())
    metadata = source.service.statuses()[-1]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"scrobbles": "bad"}))
    artifact = ArtifactMetadata(
        "history", "artifacts/history", "0" * 64, 0, "now", "test"
    )
    with pytest.raises(ValueError, match="scrobbles list"):
        build_listening_index(path, tmp_path / "failed.sqlite", artifact)
    assert metadata.exists


class BlockingStore(JsonLibraryDataStore):
    """Hold one source restore while a real old-generation request completes."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.block = False
        self.entered = Event()
        self.release = Event()

    def restore(
        self,
        name: ArtifactName,
        metadata: ArtifactMetadata,
        *,
        revision: str,
        destination: Path,
    ) -> None:
        if self.block:
            self.entered.set()
            assert self.release.wait(5)
        super().restore(name, metadata, revision=revision, destination=destination)


async def test_readers_remain_available_during_snapshot_acquisition(
    tmp_path: Path,
) -> None:
    store = BlockingStore(tmp_path / "store")
    fixture = listening_fixture(tmp_path, store)
    fixture.publish(sample_history())
    token = await ready(fixture)
    fixture.publish([scrobble("2024-01-01T12:00:00", "Replacement")])
    store.block = True
    worker = Thread(target=fixture.runtime.refresh_source)
    worker.start()
    try:
        assert await asyncio.to_thread(store.entered.wait, 5)
        with fixture.runtime.acquire(token) as reader:
            assert reader.counts(QUERY).scrobbles == 7
    finally:
        store.release.set()
        await asyncio.to_thread(worker.join, 5)
        await fixture.runtime.close()
    assert not worker.is_alive()


async def test_cancelled_shutdown_drains_worker_before_removing_storage(
    tmp_path: Path,
) -> None:
    store = BlockingStore(tmp_path / "store")
    fixture = listening_fixture(tmp_path, store)
    fixture.publish(sample_history())
    store.block = True
    root = fixture.runtime._root
    fixture.runtime.status()
    try:
        assert await asyncio.to_thread(store.entered.wait, 5)
        closing = asyncio.create_task(fixture.runtime.close())
        await asyncio.sleep(0)
        closing.cancel()
        await asyncio.sleep(0)
        assert root.exists()
    finally:
        store.release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert not root.exists()
