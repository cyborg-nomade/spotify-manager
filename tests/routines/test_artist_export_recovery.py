"""Exercise source recovery through complete artist refreshes and publication."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.core.library_data.models import ARTIFACT_FILENAMES
from spotify_manager.core.library_data.service import LibraryDataService
from spotify_manager.domain.library_analysis_values import LibraryAnalysisCancelledError
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.domain.library_analysis_values import LibrarySyncSummary
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)
from spotify_manager.infrastructure.space_library_export import SpaceLibraryExport
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.routines import analyse_library
from tests.routines.test_analyse_library import FakeSpotify
from tests.routines.test_analyse_library import artist
from tests.routines.test_analyse_library import ids
from tests.routines.test_analyse_library import paths_for
from tests.support.runtime_resources import CancellationFlag
from tests.support.runtime_resources import RetryDecision


@dataclass(frozen=True)
class ArtistRefresh:
    """Own isolated Spotify, source, and durable-publication observations.

    Args:
        paths: Independent analysis and canonical file paths.
        catalog: Scripted Spotify observations.
        service: Real local durable-data service.
        cached: Downloaded source fixture, replaceable for failure cases.
    """

    paths: LibraryAnalysisPaths
    catalog: FakeSpotify
    service: LibraryDataService
    cached: Path

    def run(
        self,
        full: bool = False,
        cancellation: CancellationFlag | None = None,
        retry: RetryDecision | None = None,
    ) -> LibrarySyncSummary:
        """Run the public synchronous entry with isolated external resources.

        Args:
            full: Whether to discover and verify the complete artist set.
            cancellation: Optional fixed operator cancellation response.
            retry: Optional recorded cooldown decision, without wall-clock waits.

        Returns:
            The complete refresh summary after durable publication.
        """
        return analyse_library.refresh_live_library_resource_routine(
            self.catalog,
            "artists",
            paths=self.paths,
            full_rebuild=full,
            cancel_check=cancellation,
            retry_wait=retry,
            retry_base_seconds=0,
            retry_max_seconds=0,
        )


def _packaged_source(paths: LibraryAnalysisPaths, mocker: MockerFixture) -> Path:
    content = YourLibraryFile(albums=[], tracks=[], artists=[artist("new")])
    payload = content.model_dump_json().encode()
    digest = hashlib.sha256(payload).hexdigest()
    paths.your_library.write_text(
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{digest}\nsize {len(payload)}\n"
    )
    cached = paths.files_dir / "downloaded.json"
    cached.write_bytes(payload)
    mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download",
        return_value=str(cached),
    )
    mocker.patch(
        "spotify_manager.bootstrap.library_analysis.configured_export_recovery",
        return_value=SpaceLibraryExport(paths.your_library, "owner/app"),
    )
    return cached


def _publication(
    paths: LibraryAnalysisPaths, mocker: MockerFixture
) -> LibraryDataService:
    targets = {}
    for name, filename in ARTIFACT_FILENAMES.items():
        targets[name] = paths.files_dir / filename
    store = JsonLibraryDataStore(paths.files_dir / "durable")
    service = LibraryDataService(store, targets)
    mocker.patch(
        "spotify_manager.bootstrap.library_data._PATH_TO_ARTIFACT",
        {paths.artists_total.resolve(): "artists"},
    )
    mocker.patch(
        "spotify_manager.bootstrap.library_data.get_library_data_service",
        return_value=service,
    )
    service.publish("artists", source="test seed")
    return service


@pytest.fixture
def refresh(tmp_path: Path, mocker: MockerFixture) -> ArtistRefresh:
    """Build a real publication workspace with a packaged pointer source.

    Args:
        tmp_path: Disposable directory for every source, mirror, and checkpoint.
        mocker: Framework patches for Hub reads and outer resource construction.

    Returns:
        A refresh that can mutate only synthetic local files.
    """
    paths = paths_for(tmp_path, "mirrors")
    paths.artists_total.write_text(json.dumps([artist("old").model_dump()]))
    cached = _packaged_source(paths, mocker)
    service = _publication(paths, mocker)
    return ArtistRefresh(paths, FakeSpotify(artists=[artist("new")]), service, cached)


@pytest.mark.parametrize("full", [False, True])
def test_recovered_export_reaches_durable_publication(
    refresh: ArtistRefresh, full: bool
) -> None:
    """Preserve recent retention and full unfollow removal after source recovery.

    Args:
        refresh: Isolated complete routine and durable-data service.
        full: Requested recent or full refresh mode.
    """
    before = refresh.service.snapshot().revision
    refresh.catalog.artist_errors = [502] if full else []
    summary = refresh.run(full)
    expected = {"new"} if full else {"old", "new"}
    assert set(ids(refresh.paths.artists_total)) == expected
    assert summary.resources[0].source == "live_verified_fallback"
    assert refresh.service.snapshot().revision != before
    status = refresh.service.statuses()[2]
    assert status.name == "artists" and status.exists and status.local_current
    assert refresh.paths.your_library.read_text().startswith("version https://git-lfs")


@pytest.mark.parametrize("full", [False, True])
def test_artist_refresh_waits_through_repeated_rate_limits_before_publication(
    refresh: ArtistRefresh, full: bool
) -> None:
    """Finish the same recent/full refresh after several follow-status cooldowns.

    Args:
        refresh: Isolated routine and real durable-data service.
        full: Whether every candidate must be verified live.
    """
    refresh.catalog.artist_errors = [502] if full else []
    refresh.catalog.artist_contains_errors = [429, 429, 429, 429]
    notices: list[analyse_library.RetryNotice] = []
    revision = refresh.service.snapshot().revision
    summary = refresh.run(full, retry=RetryDecision(True, notices))
    expected = {"new"} if full else {"old", "new"}
    assert set(ids(refresh.paths.artists_total)) == expected
    assert summary.resources[0].current == len(expected)
    assert refresh.service.snapshot().revision != revision
    cooldowns = []
    for notice in notices:
        if notice.http_status == 429:
            cooldowns.append(notice.delay_seconds)
    assert cooldowns == [60, 120, 240, 480]
    assert (
        refresh.catalog.artist_contains_calls
        == [refresh.catalog.artist_contains_calls[0]] * 5
    )


def test_cancelled_artist_cooldown_preserves_mirror_and_resumes_checkpoint(
    refresh: ArtistRefresh,
) -> None:
    """Stop without publication, then reuse accepted candidates on the next run.

    Args:
        refresh: Isolated routine and real durable-data service.
    """
    refresh.catalog.artist_contains_errors = [429]
    revision = refresh.service.snapshot().revision
    with pytest.raises(LibraryAnalysisCancelledError):
        refresh.run(retry=RetryDecision(False))
    assert ids(refresh.paths.artists_total) == ["old"]
    assert refresh.service.snapshot().revision == revision
    refresh.cached.unlink()
    refresh.run()
    assert set(ids(refresh.paths.artists_total)) == {"old", "new"}
    assert refresh.service.snapshot().revision != revision


def test_failed_source_recovery_preserves_last_durable_artist_mirror(
    refresh: ArtistRefresh,
) -> None:
    """Keep canonical bytes and durable revision when a download is incomplete.

    Args:
        refresh: Isolated complete routine and durable-data service.
    """
    original = refresh.paths.artists_total.read_bytes()
    revision = refresh.service.snapshot().revision
    refresh.cached.write_text("truncated download")
    with pytest.raises(LibrarySyncError, match="size does not match"):
        refresh.run()
    assert refresh.paths.artists_total.read_bytes() == original
    assert refresh.service.snapshot().revision == revision
    assert refresh.catalog.artist_contains_calls == []


def test_prepared_candidates_resume_without_rereading_the_export(
    refresh: ArtistRefresh,
) -> None:
    """Resume accepted candidate staging after cancellation without losing artists.

    Args:
        refresh: Isolated complete routine and durable-data service.
    """
    revision = refresh.service.snapshot().revision
    with pytest.raises(LibraryAnalysisCancelledError):
        refresh.run(cancellation=CancellationFlag(True))
    assert refresh.service.snapshot().revision == revision
    refresh.cached.unlink()
    summary = refresh.run()
    assert set(ids(refresh.paths.artists_total)) == {"old", "new"}
    assert summary.resources[0].current == 2
    assert refresh.service.snapshot().revision != revision


def test_incomplete_follow_response_cannot_publish_a_partial_mirror(
    refresh: ArtistRefresh, mocker: MockerFixture
) -> None:
    """Retain the previous mirror if Spotify omits a candidate verification status.

    Args:
        refresh: Isolated complete routine and durable-data service.
        mocker: Framework patch for a malformed Spotify response.
    """
    revision = refresh.service.snapshot().revision
    mocker.patch.object(
        refresh.catalog, "current_user_following_artists", return_value=[]
    )
    with pytest.raises(LibrarySyncError, match="incomplete artist-follow"):
        refresh.run()
    assert ids(refresh.paths.artists_total) == ["old"]
    assert refresh.service.snapshot().revision == revision
