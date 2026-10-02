"""Verify selected-source order and preparation without any production runtime."""

from pathlib import Path

import pytest

from spotify_manager.application.upload_run import Preparation
from spotify_manager.application.upload_run import prepare
from spotify_manager.application.upload_values import LASTFM_FILENAME
from spotify_manager.application.upload_values import YOUR_LIBRARY_FILENAME
from spotify_manager.domain.upload_manifest import LibraryFilesUploadError
from spotify_manager.infrastructure.upload_files import build_parts


def read_export(path: Path, key: str) -> tuple[bytes, int]:
    """Return the original selected source bytes from a deterministic fake.

    Args:
        path: Original selected source path.
        key: Original shallow required array.

    Returns:
        Original raw bytes and row count.
    """
    expected = "tracks" if path.name == YOUR_LIBRARY_FILENAME else "scrobbles"
    assert key == expected
    return b'{"items": []}', 0


@pytest.mark.parametrize("library,lastfm", [(True, True), (True, False), (False, True)])
def test_preparation_retains_selection_order(
    library: bool, lastfm: bool, tmp_path: Path
) -> None:
    """Prepare exact manifests without materializing a single file.

    Args:
        library: Original Spotify export selection.
        lastfm: Original history selection.
        tmp_path: Isolated managed directory.
    """
    plan = prepare(
        Preparation(read_export, build_parts),
        tmp_path,
        library,
        lastfm,
        "repo",
        "revision",
    )
    names = []
    if library:
        names.append(YOUR_LIBRARY_FILENAME)
    if lastfm:
        names.append(LASTFM_FILENAME)
    assert [resource.name for resource in plan.resources] == names
    assert bool(plan.lastfm_parts) is lastfm
    assert plan.upload_file_count == len(names) + len(plan.lastfm_parts)
    assert plan.upload_size_bytes >= 12 * len(names)
    assert plan.repo_id == "repo" and plan.revision == "revision"
    assert list(tmp_path.iterdir()) == []


def test_preparation_rejects_empty_selection(tmp_path: Path) -> None:
    """Reject no selection before invoking any external observation.

    Args:
        tmp_path: Isolated managed directory.
    """
    with pytest.raises(LibraryFilesUploadError, match="at least one"):
        prepare(
            Preparation(read_export, build_parts),
            tmp_path,
            False,
            False,
            "repo",
            "main",
        )
