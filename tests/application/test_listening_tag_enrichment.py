"""Explicit bounded metadata work, failure retention and cancellation ownership."""

import asyncio
from pathlib import Path
from threading import Event

import pytest

from spotify_manager.application import listening_tags
from spotify_manager.application.listening_tag_ports import TagFetchRequest
from spotify_manager.application.listening_tag_ports import TagSourceError
from spotify_manager.application.listening_tags import ListeningTagEnrichment
from spotify_manager.domain.listening_tag_values import ArtistTagMetadata
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.listening.tag_cache import ArtistTagCache
from tests.support.listening_tags import FixtureTagSource
from tests.support.listening_tags import tag_metadata


def request(count: int = 2) -> TagFetchRequest:
    """Create a bounded set of explicit public artist requests."""
    rows = []
    for index in range(count):
        name = str(index)
        rows.append(RankedEntity(listening_identity((name,)), name, "", 1, 1.0))
    return TagFetchRequest(tuple(rows), "v1-fixture")


async def completed(stage: ListeningTagEnrichment) -> None:
    """Yield until a small synthetic batch completes without network or sleeps."""
    for _attempt in range(1000):
        if stage.status().state not in ("running", "cancelling"):
            return
        await asyncio.sleep(0.001)
    raise AssertionError("Synthetic tag batch did not finish.")


@pytest.mark.asyncio
async def test_one_explicit_batch_persists_complete_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated start cannot duplicate provider work and completed data persists."""
    monkeypatch.setattr(listening_tags, "REQUEST_INTERVAL", 0)
    source = FixtureTagSource()
    cache = ArtistTagCache(tmp_path)
    stage = ListeningTagEnrichment(cache, source)
    assert stage.status().state == "idle"
    stage.start(request())
    assert stage.start(request(3)).total == 2
    await completed(stage)
    assert source.names == ["0", "1"]
    assert stage.status().completed == stage.status().cached_artists == 2
    assert stage.status().state == "complete"
    await stage.close()
    with pytest.raises(TagSourceError):
        stage.start(request())


@pytest.mark.asyncio
async def test_provider_failure_preserves_cached_tags_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed provider never overwrites available observations or history."""
    monkeypatch.setattr(listening_tags, "REQUEST_INTERVAL", 0)
    cache = ArtistTagCache(tmp_path)
    cache.write(tag_metadata())
    before = cache.current()
    source = FixtureTagSource(fail=True)
    stage = ListeningTagEnrichment(cache, source)
    stage.start(request())
    await completed(stage)
    assert stage.status().state == "error" and cache.current() is before
    source.fail = False
    stage.start(request(1))
    await completed(stage)
    assert stage.status().state == "complete"
    await stage.close()


@pytest.mark.asyncio
async def test_cancellation_before_start_finishes_and_bounds_are_enforced(
    tmp_path: Path,
) -> None:
    """Early cancellation cannot leave a permanently busy lookup state."""
    source = FixtureTagSource()
    stage = ListeningTagEnrichment(ArtistTagCache(tmp_path), source)
    with pytest.raises(ValueError):
        stage.start(request(51))
    stage.start(request())
    stage.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert stage.status().state == "cancelled"
    source.configured = False
    assert not stage.status().configured
    with pytest.raises(TagSourceError):
        stage.start(request())
    await stage.close()


@pytest.mark.asyncio
async def test_empty_batch_completes_without_public_reads(tmp_path: Path) -> None:
    """A fully cached selection can finish with no provider traffic."""
    source = FixtureTagSource()
    stage = ListeningTagEnrichment(ArtistTagCache(tmp_path), source)
    stage.start(request(0))
    await completed(stage)
    assert stage.status().state == "complete" and source.names == []
    await stage.close()


class DelayedCache(ArtistTagCache):
    """Hold one concrete cache commit at a controlled cancellation boundary."""

    def __init__(self, root: Path, started: Event, release: Event) -> None:
        """Bind the synthetic cache and test-owned synchronization events."""
        super().__init__(root)
        self.started = started
        self.release = release

    def write(self, metadata: ArtistTagMetadata) -> None:
        """Finish an already-started commit before cancellation can discard it."""

        self.started.set()
        assert self.release.wait(5)
        super().write(metadata)


@pytest.mark.asyncio
async def test_cancellation_drains_a_complete_cache_commit_and_counts_it(
    tmp_path: Path,
) -> None:
    """A cancelled request retains an atomically completed cache observation."""
    started, release = Event(), Event()
    cache = DelayedCache(tmp_path, started, release)
    stage = ListeningTagEnrichment(cache, FixtureTagSource())
    stage.start(request(1))
    while not started.is_set():
        await asyncio.sleep(0.001)
    assert stage.cancel().state == "cancelling"
    await asyncio.sleep(0.01)
    assert stage.status().state == "cancelling"
    release.set()
    await completed(stage)
    assert stage.status().state == "cancelled"
    assert stage.status().completed == stage.status().cached_artists == 1
    await stage.close()


@pytest.mark.asyncio
async def test_cache_failure_is_visible_without_exposing_partial_metadata(
    tmp_path: Path,
) -> None:
    """Invalid derived storage is independent of provider and history readiness."""
    (tmp_path / "artist-tags-v1.sqlite").write_bytes(b"broken")
    cache = ArtistTagCache(tmp_path)
    stage = ListeningTagEnrichment(cache, FixtureTagSource())
    assert not stage.status().cache_available
    assert "cache unavailable" in stage.status().message
    stage.start(request(1))
    await completed(stage)
    assert stage.status().state == "error"
    assert stage.status().completed == 0 and cache.current().entries == ()
    await stage.close()
