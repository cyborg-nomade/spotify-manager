"""Verify unusual resumable states and original malformed-page failure boundaries."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application import library_analysis_artists as artists
from spotify_manager.application import library_analysis_offsets as offsets
from spotify_manager.application.library_analysis_export import prepare_export_resource
from spotify_manager.application.library_analysis_publication import finalize_mirrors
from spotify_manager.application.library_analysis_run import refresh_resource
from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.application.library_analysis_values import LibraryModel
from spotify_manager.domain.library_analysis_values import IncompleteLiveResourceError
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.domain.library_analysis_values import ResourceName
from spotify_manager.domain.library_analysis_values import ResourceSyncSummary
from spotify_manager.domain.library_analysis_values import (
    _FollowedArtistsEndpointUnavailableError,
)
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.utils.sorting import album_sort_key
from tests.application.library_analysis_memory import AnalysisMemory
from tests.application.library_analysis_memory import memory_session
from tests.application.test_library_analysis_sequence import _publication


def _artist(identity: str) -> YourLibraryArtist:
    return YourLibraryArtist(name=identity, uri=f"spotify:artist:{identity}")


def _album(identity: str) -> YourLibraryAlbum:
    return YourLibraryAlbum(
        artist="Credit", album=identity, uri=f"spotify:album:{identity}"
    )


def _page(items: list[object], next_cursor: str | None = None) -> dict[str, object]:
    return {
        "items": items,
        "total": 2,
        "next": "link" if next_cursor else None,
        "cursors": {"after": next_cursor},
    }


def test_empty_offset_page_with_next_is_checkpointed_and_reported_before_failure(
    tmp_path: Path,
) -> None:
    """Retain original empty-next failure after accepted staging, audit and progress.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory(pages=[{"items": [], "total": 3, "next": "link"}])
    session = memory_session(memory, tmp_path)
    with pytest.raises(IncompleteLiveResourceError, match="empty albums page"):
        offsets.scan_initial(session, "albums")
    state = session.checkpoint["resources"]["albums"]
    assert (state["status"], state["offset"], state["pages"]) == ("scanning", 0, 1)
    assert memory.effects[-1] == ("progress", ("albums", 0, 3, "Reading live API"))
    assert memory.effects[-2][0] == "page_saved"


def test_invalid_offset_rows_are_skipped_without_reducing_the_raw_offset(
    tmp_path: Path,
) -> None:
    """Keep original raw-row paging even when model conversion drops unusable rows.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory(
        pages=[{"items": [None, _album("a")], "total": True, "next": None}]
    )
    session = memory_session(memory, tmp_path)
    offsets.scan_initial(session, "albums")
    state = session.checkpoint["resources"]["albums"]
    assert (state["offset"], state["skipped"], state["total"]) == (2, 1, True)
    assert memory.arrays[session.paths.stage("albums")] == [_album("a")]


def test_artist_cursor_scan_and_reconciliation_restart_each_complete_pass(
    tmp_path: Path,
) -> None:
    """Retain original full artist rescans and accepted cursor progression.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    pages = [_page([_artist("a")], "cursor"), _page([_artist("b")])]
    memory = AnalysisMemory(pages=pages * 3)
    session = memory_session(memory, tmp_path)
    artists.scan_initial(session)
    artists.reconcile(session)
    assert session.checkpoint["resources"]["artists"]["status"] == "complete"
    cursors = [value for name, value in memory.effects if name == "cursor"]
    assert cursors == [None, "cursor", None, "cursor", None, "cursor"]
    assert memory.arrays[session.paths.stage("artists")] == [_artist("a"), _artist("b")]


@pytest.mark.parametrize("cursor", [None, "same"])
def test_nonadvancing_artist_cursor_fails_after_accepted_page(
    tmp_path: Path, cursor: str | None
) -> None:
    """Preserve original absent/equal cursor checks after checkpoint and progress.

    Args:
        tmp_path: Independent path names for memory authority.
        cursor: Original absent or repeated raw cursor.
    """
    page = _page([_artist("a")])
    page.update(next="link", cursors={"after": cursor})
    memory = AnalysisMemory(pages=[page])
    session = memory_session(memory, tmp_path)
    session.checkpoint["resources"]["artists"]["after"] = "same"
    with pytest.raises(IncompleteLiveResourceError, match="did not advance"):
        artists.scan_initial(session)
    assert memory.arrays[session.paths.stage("artists")] == [_artist("a")]
    assert memory.effects[-1][0] == "progress"


def test_direct_artist_budget_stops_before_another_live_read(tmp_path: Path) -> None:
    """Retain original bounded direct discovery and fallback reason.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory()
    session = memory_session(memory, tmp_path)
    session.checkpoint["resources"]["artists"]["pages"] = 25
    with pytest.raises(
        _FollowedArtistsEndpointUnavailableError, match="bounded page budget"
    ):
        artists.scan_initial(session)
    assert [name for name, _value in memory.effects] == ["write"]


def test_completed_artists_are_read_for_progress_without_rescanning(
    tmp_path: Path,
) -> None:
    """Preserve original completed-resource duplicate counts and live-read guard.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory()
    session = memory_session(memory, tmp_path)
    session.checkpoint["resources"]["artists"]["status"] = "complete"
    memory.arrays[session.paths.stage("artists")] = [_artist("a"), _artist("a")]
    artists.reconcile(session)
    assert memory.effects == [
        ("models", session.paths.stage("artists")),
        ("progress", ("artists", 1, 1, "Complete")),
    ]


def test_fallback_already_prepared_does_not_replace_accepted_candidates(
    tmp_path: Path,
) -> None:
    """Retain original verification-state guard before any source or staging effect.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory()
    session = memory_session(memory, tmp_path)
    session.checkpoint["resources"]["artists"]["status"] = "verifying_fallback"
    artists.prepare_verification(session, full_rebuild=True, reason="already accepted")
    assert memory.effects == []


@pytest.mark.parametrize("response", [None, [], [True, False]])
def test_incomplete_artist_verification_keeps_original_candidate_offset(
    tmp_path: Path, response: object
) -> None:
    """Retain original sequence-length validation before staged rows or checkpoints.

    Args:
        tmp_path: Independent path names for memory authority.
        response: Original malformed or incomplete verification response.
    """
    memory = AnalysisMemory(follow_response=response)
    session = memory_session(memory, tmp_path)
    memory.arrays[artists.candidate_path(session)] = [_artist("a")]
    with pytest.raises(IncompleteLiveResourceError, match="incomplete artist-follow"):
        artists.verify(session)
    assert memory.effects[-1] == ("following", ["a"])
    assert "candidate_index" not in session.checkpoint["resources"]["artists"]


@pytest.mark.parametrize("progress", [True, False])
def test_completed_export_resource_uses_staging_without_reprocessing_source(
    tmp_path: Path,
    progress: bool,
) -> None:
    """Retain original completed export resume and progress counts.

    Args:
        tmp_path: Independent path names for memory authority.
        progress: Original optional progress presence.
    """
    memory = AnalysisMemory()
    session = memory_session(memory, tmp_path, progress)
    session.checkpoint["resources"]["albums"]["status"] = "complete"
    memory.arrays[session.paths.stage("albums")] = [_album("stored")]
    result = prepare_export_resource(
        session, "albums", [_album("source")], YourLibraryAlbum, album_sort_key
    )
    assert result == [_album("stored")]
    if progress:
        assert memory.effects[-1] == ("progress", ("albums", 1, 1, "Complete"))
    else:
        assert memory.effects == [("models", session.paths.stage("albums"))]


def test_large_export_observes_original_coarse_progress_and_cancellation_boundaries(
    tmp_path: Path,
) -> None:
    """Retain original roughly one-percent progress steps for large exports.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory()
    session = memory_session(memory, tmp_path)
    source = [_album(str(index)) for index in range(201)]
    prepare_export_resource(session, "albums", source, YourLibraryAlbum, album_sort_key)
    progress: list[tuple[str, int, int, str]] = []
    for name, value in memory.effects:
        if name == "progress":
            progress.append(cast(tuple[str, int, int, str], value))
    assert [value[1] for value in progress[:4]] == [0, 2, 4, 6]
    assert [value[1] for value in progress[-2:]] == [201, 201]


def _memory_backup(
    paths: LibraryAnalysisPaths,
    run_id: str,
    resource: ResourceName,
    target: Path,
    previous: Sequence[LibraryModel],
    current: Sequence[LibraryModel],
    summary: ResourceSyncSummary,
) -> Path:
    return paths.backups_dir / run_id


def test_invalid_publication_manifest_fails_before_any_output_is_replaced(
    tmp_path: Path,
) -> None:
    """Preserve original resumed-publication shape validation before output writes.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory()
    session = memory_session(memory, tmp_path)
    session.checkpoint.update(
        {"status": "finalizing", "backup_dir": str(tmp_path / "backup")}
    )
    with pytest.raises(
        LibrarySyncError, match="live-mirror backup manifest is invalid"
    ):
        finalize_mirrors(session, _publication(session.files), [], [])
    assert memory.effects == [("read", tmp_path / "backup/manifest.json")]


def test_full_artist_resume_verifies_accepted_candidates_without_rediscovery(
    tmp_path: Path,
) -> None:
    """Retain original fallback restart authority instead of reopening cursor scans.

    Args:
        tmp_path: Independent path names for memory authority.
    """
    memory = AnalysisMemory(follow_response=[True])
    session = memory_session(memory, tmp_path)
    state = session.checkpoint["resources"]["artists"]
    state.update(
        {
            "status": "verifying_fallback",
            "candidate_index": 0,
            "retained": 0,
            "total": 1,
            "source": "live_verified_fallback",
        }
    )
    memory.arrays[artists.candidate_path(session)] = [_artist("accepted")]
    publication = replace(_publication(session.files), resource_backup=_memory_backup)
    result = refresh_resource(session, publication, "artists", True)
    assert result.resources[0].source == "live_verified_fallback"
    assert result.resources[0].current == 1
    assert not any(name == "cursor" for name, _value in memory.effects)
    assert memory.arrays[session.paths.artists_total] == [_artist("accepted")]
