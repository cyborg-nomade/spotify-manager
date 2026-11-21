"""Verified multi-artifact reads, bounded caching and generation lifecycle."""

from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from spotify_manager.application.listening_ports import ListeningNotReadyError
from spotify_manager.application.listening_ports import ListeningVersionError
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.library_source import LibraryPublications
from tests.support.listening import ListeningFixture
from tests.support.listening import listening_fixture
from tests.support.listening_library import album
from tests.support.listening_library import publish_collection


def test_three_sources_share_one_revision_without_hydrating_or_writing(
    tmp_path: Path,
) -> None:
    fixture = listening_fixture(tmp_path)
    publish_collection(fixture, "albums", [album(), album()])
    publish_collection(
        fixture,
        "tracks",
        [{"artist": "Alpha", "track": "Song", "uri": "spotify:track:" + "a" * 22}],
    )
    publish_collection(
        fixture, "artists", [{"name": "Alpha", "uri": "spotify:artist:" + "b" * 22}]
    )
    before = fixture.service.snapshot()
    fixture.service.paths["albums"].write_text("unrelated working changes")
    source = LibraryPublications(fixture.service)
    result = source.read()
    assert result.revision == before.revision
    assert [item.state for item in result.sources] == ["ready"] * 3
    assert [item.entries for item in result.sources] == [1, 1, 1]
    assert len(result.entries) == 3
    assert fixture.service.paths["albums"].read_text() == "unrelated working changes"
    assert fixture.service.snapshot().revision == before.revision
    with patch.object(
        fixture.service,
        "export_at_snapshot",
        side_effect=AssertionError("cache bypass"),
    ):
        assert source.read().snapshot == result.snapshot


@pytest.mark.parametrize(
    "row",
    [
        None,
        {},
        {"artist": "Alpha", "album": "", "uri": "spotify:album:" + "a" * 22},
        {"artist": "Alpha", "album": "Record", "uri": "javascript:alert(1)"},
        {"artist": "Alpha", "album": "Record", "uri": "spotify:track:" + "a" * 22},
    ],
)
def test_invalid_rows_make_the_entire_collection_unknown(
    tmp_path: Path, row: object
) -> None:
    fixture = listening_fixture(tmp_path)
    publish_collection(fixture, "albums", [album(), row])
    result = LibraryPublications(fixture.service).read()
    assert [item.state for item in result.sources] == ["missing", "error", "missing"]
    assert result.entries == ()
    assert result.sources[1].sha256 and result.sources[1].published_at


def test_empty_collection_is_known_while_corrupt_blob_is_unknown(
    tmp_path: Path,
) -> None:
    fixture = listening_fixture(tmp_path)
    publish_collection(fixture, "albums", [])
    source = LibraryPublications(fixture.service)
    empty = source.read()
    assert empty.sources[1].state == "ready" and empty.sources[1].entries == 0
    blob = tmp_path / "store/artifacts/albums_total_new.json.gz"
    blob.write_bytes(b"broken compressed data")
    assert LibraryPublications(fixture.service).read().sources[1].state == "error"
    assert source.read().sources[1].state == "ready"


def test_pinned_revision_conflict_rejects_a_mixed_generation(tmp_path: Path) -> None:
    fixture = listening_fixture(tmp_path)
    publish_collection(fixture, "albums", [album()])
    source = LibraryPublications(fixture.service)
    with patch.object(
        fixture.service,
        "export_at_snapshot",
        side_effect=LibraryDataConflictError("changed"),
    ):
        with pytest.raises(LibraryDataConflictError):
            source.read()


@pytest.mark.asyncio
async def test_generation_expiry_stale_recovery_and_close(tmp_path: Path) -> None:
    fixture = listening_fixture(tmp_path)
    runtime = LibraryRuntime(fixture.service)
    with pytest.raises(ListeningNotReadyError):
        runtime.acquire("l1-" + "0" * 64)
    assert runtime.status().state == "building"
    await runtime.close()
    assert runtime.status().snapshot is None
    runtime = LibraryRuntime(fixture.service)
    tokens = []
    for identity in range(3):
        publish_collection(fixture, "albums", [album(identity=identity)])
        runtime.refresh_source()
        token = LibraryPublications(fixture.service).read().snapshot
        tokens.append(token)
    with pytest.raises(ListeningVersionError):
        runtime.acquire(tokens[0])
    retained = runtime.acquire(tokens[1])
    with patch.object(fixture.service, "snapshot", side_effect=OSError("offline")):
        runtime.refresh_source()
    assert runtime._status(False).state == "stale"
    assert retained.entries[0].uri.endswith("1".zfill(22))
    runtime.refresh_source()
    assert runtime._status(False).state == "ready"
    await runtime.close()
    await fixture.runtime.close()


@pytest.mark.asyncio
async def test_initial_manifest_failure_is_recoverable(tmp_path: Path) -> None:
    fixture = listening_fixture(tmp_path)
    runtime = LibraryRuntime(fixture.service)
    with patch.object(
        fixture.service, "snapshot", side_effect=ValueError("invalid manifest")
    ):
        runtime.refresh_source()
    assert runtime._status(False).state == "error"
    runtime.refresh_source()
    assert runtime._status(False).sources[0].state == "missing"
    await runtime.close()
    await fixture.runtime.close()


@pytest.mark.parametrize("content", ["not-json", "{}"])
def test_invalid_decoded_publication_shape_is_rejected(
    tmp_path: Path, content: str
) -> None:
    """Reject invalid JSON and wrong roots even after checksum verification."""
    from spotify_manager.infrastructure.listening.library_source import _decode

    path = tmp_path / "published.json"
    path.write_text(content)
    with pytest.raises(ValueError):
        _decode(path, "album")


class DelayedPublications(LibraryPublications):
    """Hold a concrete publication read until a controlled shutdown boundary."""

    def __init__(
        self, fixture: ListeningFixture, started: Event, release: Event
    ) -> None:
        """Bind only test-owned synchronization and the synthetic service."""
        super().__init__(fixture.service)
        self.started = started
        self.release = release

    def read(self) -> LibraryCatalog:
        """Hold the real source acquisition without changing its publication."""
        self.started.set()
        assert self.release.wait(5)
        return super().read()


@pytest.mark.asyncio
async def test_one_worker_is_drained_even_if_shutdown_is_cancelled(
    tmp_path: Path,
) -> None:
    """A repeated refresh cannot duplicate work or outlive cancelled cleanup."""
    import asyncio

    fixture = listening_fixture(tmp_path)
    runtime = LibraryRuntime(fixture.service)
    started, release = Event(), Event()
    runtime._source = DelayedPublications(fixture, started, release)
    assert runtime.status().checking
    first_task = runtime._task
    assert runtime.status(refresh=True).checking and runtime._task is first_task
    while not started.is_set():
        await asyncio.sleep(0.001)
    closing = asyncio.create_task(runtime.close())
    await asyncio.sleep(0.01)
    closing.cancel()
    await asyncio.sleep(0.01)
    assert not closing.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert runtime._generations == {}
    await fixture.runtime.close()
