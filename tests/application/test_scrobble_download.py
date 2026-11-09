"""History download use case preserves ownership and distinguishes absence."""

from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest

from spotify_manager.application.scrobble_download import MissingScrobbleHistoryError
from spotify_manager.application.scrobble_download import ScrobbleDownloads
from spotify_manager.application.scrobble_download import (
    prepare_scrobble_history_download,
)
from spotify_manager.core.library_data.models import LibraryDataConfigurationError
from tests.support.scrobble_downloads import HISTORY
from tests.support.scrobble_downloads import download_fixture
from tests.support.scrobble_downloads import publish_history


def test_use_case_returns_exact_owned_published_bytes(tmp_path: Path) -> None:
    """The consumer owns a verified original file, rather than reconstructed JSON.

    Args:
        tmp_path: Independent working and durable directories.
    """
    fixture = download_fixture(tmp_path)
    publish_history(fixture)
    download = prepare_scrobble_history_download(fixture.files)
    assert download.path.read_bytes() == HISTORY
    assert download.metadata.filename == fixture.working.name
    download.close()
    assert not download.path.exists() and fixture.working.read_bytes() == HISTORY


def test_missing_history_does_not_fall_back_to_unpublished_working_file(
    tmp_path: Path,
) -> None:
    """A packaged or partial working export is not a published download.

    Args:
        tmp_path: Independent working and durable directories.
    """
    fixture = download_fixture(tmp_path)
    fixture.working.write_bytes(HISTORY)
    with pytest.raises(MissingScrobbleHistoryError, match="Sync history first"):
        prepare_scrobble_history_download(fixture.files)
    assert list(fixture.spool.iterdir()) == []


def test_storage_failures_retain_their_existing_boundary() -> None:
    """Storage failures do not become missing-history success."""
    error = LibraryDataConfigurationError("store unavailable")
    downloads = Mock(spec=ScrobbleDownloads)
    downloads.prepare.side_effect = error
    with pytest.raises(LibraryDataConfigurationError) as caught:
        prepare_scrobble_history_download(cast(ScrobbleDownloads, downloads))
    assert caught.value is error
