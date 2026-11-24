"""Explicit bounded metadata work, failure retention and cancellation ownership."""

import asyncio
from pathlib import Path
from threading import Event

import pytest

from spotify_manager.application import listening_covers
from spotify_manager.application.listening_cover_ports import CoverFetchRequest
from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.application.listening_covers import ListeningCoverEnrichment
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.listening.cover_cache import AlbumCoverCache
from tests.support.listening_covers import FixtureCoverSource
from tests.support.listening_covers import cover_result


def request(count: int = 2) -> CoverFetchRequest:
    """Create a bounded set of explicit public album requests.

    Args:
        count: Number of captured requests or exact-name candidates.

    Returns:
        Captured synthetic album names and history version.
    """
    rows = []
    for index in range(count):
        name = str(index)
        rows.append(
            RankedEntity(listening_identity(("Alpha", name)), name, "Alpha", 1, 1.0)
        )
    return CoverFetchRequest(tuple(rows), "v1-fixture")


async def completed(stage: ListeningCoverEnrichment) -> None:
    """Yield until a small synthetic batch completes without network or sleeps.

    Args:
        stage: Owned explicit cover-enrichment stage under test.
    """
    for _attempt in range(1000):
        if stage.status().state not in ("running", "cancelling"):
            return
        await asyncio.sleep(0.001)
    raise AssertionError("Synthetic tag batch did not finish.")


@pytest.mark.asyncio
async def test_one_explicit_batch_persists_complete_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repeated start cannot duplicate provider work and completed data persists.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
        monkeypatch: Scoped replacements for timing and concrete integration boundaries.
    """
    monkeypatch.setattr(listening_covers, "REQUEST_INTERVAL", 0)
    source = FixtureCoverSource()
    cache = AlbumCoverCache(tmp_path)
    stage = ListeningCoverEnrichment(cache, source)
    assert stage.status().state == "idle"
    stage.start(request())
    assert stage.start(request(3)).total == 2
    await completed(stage)
    assert source.names == ["0", "1"]
    assert stage.status().completed == stage.status().cached_albums == 2
    assert stage.status().state == "complete"
    await stage.close()
    with pytest.raises(CoverSourceError):
        stage.start(request())


@pytest.mark.asyncio
async def test_provider_failure_preserves_cached_artwork_and_can_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed provider never overwrites available observations or history.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
        monkeypatch: Scoped replacements for timing and concrete integration boundaries.
    """
    monkeypatch.setattr(listening_covers, "REQUEST_INTERVAL", 0)
    cache = AlbumCoverCache(tmp_path)
    cache.write(cover_result())
    before = cache.current()
    source = FixtureCoverSource(fail=True)
    stage = ListeningCoverEnrichment(cache, source)
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
    """Early cancellation cannot leave a permanently busy lookup state.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
    """
    source = FixtureCoverSource()
    stage = ListeningCoverEnrichment(AlbumCoverCache(tmp_path), source)
    with pytest.raises(ValueError):
        stage.start(request(11))
    stage.start(request())
    stage.cancel()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert stage.status().state == "cancelled"
    source.configured = False
    assert not stage.status().configured
    with pytest.raises(CoverSourceError):
        stage.start(request())
    await stage.close()


class QuickFixtureCover:
    """Make only the final cover of the synthetic batch available."""

    available = True

    async def fetch(self, album: RankedEntity) -> CoverFetchResult | None:
        """Return a fast result for the last requested album."""
        return cover_result(album.name, album.artist) if album.name == "2" else None


@pytest.mark.asyncio
async def test_fast_cover_pass_saves_later_covers_even_if_fallback_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first slow fallback cannot delay exact matches later in the batch."""
    monkeypatch.setattr(listening_covers, "REQUEST_INTERVAL", 0)
    cache = AlbumCoverCache(tmp_path)
    fallback = FixtureCoverSource(fail=True)
    stage = ListeningCoverEnrichment(cache, fallback, QuickFixtureCover())
    stage.start(request(3))
    await completed(stage)
    assert stage.status().state == "error" and stage.status().completed == 1
    assert fallback.names == ["0"]
    assert tuple(item.album_name for item in cache.current().entries) == ("2",)
    await stage.close()


@pytest.mark.asyncio
async def test_empty_batch_completes_without_public_reads(tmp_path: Path) -> None:
    """A fully cached selection can finish with no provider traffic.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
    """
    source = FixtureCoverSource()
    stage = ListeningCoverEnrichment(AlbumCoverCache(tmp_path), source)
    stage.start(request(0))
    await completed(stage)
    assert stage.status().state == "complete" and source.names == []
    await stage.close()


class DelayedCache(AlbumCoverCache):
    """Hold one concrete cache commit at a controlled cancellation boundary."""

    def __init__(self, root: Path, started: Event, release: Event) -> None:
        """Bind the synthetic cache and test-owned synchronization events.

        Args:
            root: Test-owned derived-cache directory.
            started: Event marking an active blocking operation.
            release: Event allowing the controlled blocking operation to finish.
        """
        super().__init__(root)
        self.started = started
        self.release = release

    def write(self, metadata: CoverFetchResult) -> None:
        """Finish an already-started commit before cancellation can discard it.

        Args:
            metadata: Complete synthetic observation and optional image bytes.
        """

        self.started.set()
        assert self.release.wait(5)
        super().write(metadata)


@pytest.mark.asyncio
async def test_cancellation_drains_a_complete_cache_commit_and_counts_it(
    tmp_path: Path,
) -> None:
    """A cancelled request retains an atomically completed cache observation.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
    """
    started, release = Event(), Event()
    cache = DelayedCache(tmp_path, started, release)
    stage = ListeningCoverEnrichment(cache, FixtureCoverSource())
    stage.start(request(1))
    while not started.is_set():
        await asyncio.sleep(0.001)
    assert stage.cancel().state == "cancelling"
    await asyncio.sleep(0.01)
    assert stage.status().state == "cancelling"
    release.set()
    await completed(stage)
    assert stage.status().state == "cancelled"
    assert stage.status().completed == stage.status().cached_albums == 1
    await stage.close()


@pytest.mark.asyncio
async def test_cache_failure_is_visible_without_exposing_partial_metadata(
    tmp_path: Path,
) -> None:
    """Invalid derived storage is independent of provider and history readiness.

    Args:
        tmp_path: Isolated test-owned directory for derived metadata and history.
    """
    (tmp_path / "album-covers-v1.sqlite").write_bytes(b"broken")
    cache = AlbumCoverCache(tmp_path)
    stage = ListeningCoverEnrichment(cache, FixtureCoverSource())
    assert not stage.status().cache_available
    assert "cache unavailable" in stage.status().message
    stage.start(request(1))
    await completed(stage)
    assert stage.status().state == "error"
    assert stage.status().completed == 0 and cache.current().entries == ()
    await stage.close()
