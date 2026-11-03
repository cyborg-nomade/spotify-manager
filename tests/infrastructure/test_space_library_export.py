"""Verify exact-content recovery of a source export packaged as a Git LFS pointer."""

import hashlib
import json
from pathlib import Path

import pytest
from httpx import ConnectError
from httpx import Request
from httpx import Response
from huggingface_hub.errors import HfHubHTTPError
from huggingface_hub.errors import LocalEntryNotFoundError
from pydantic import ValidationError
from pytest_mock import MockerFixture

from spotify_manager.application.library_analysis_values import LibraryAnalysisPaths
from spotify_manager.bootstrap.library_analysis import configured_export_recovery
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.infrastructure.library_analysis_storage import AnalysisStorage
from spotify_manager.infrastructure.space_library_export import SpaceLibraryExport
from spotify_manager.infrastructure.space_library_export import export_pointer
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile


def _content() -> bytes:
    artist = YourLibraryArtist(name="Export artist", uri="spotify:artist:export")
    return (
        YourLibraryFile(albums=[], tracks=[], artists=[artist])
        .model_dump_json()
        .encode()
    )


def _pointer(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{digest}\nsize {len(content)}\n"
    )


def _storage(paths: LibraryAnalysisPaths) -> AnalysisStorage:
    return AnalysisStorage(
        SpaceLibraryExport(paths.your_library, "owner/app", "secret")
    )


def test_export_pointer_recovery_retains_every_candidate_and_source_bytes(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Resolve the pointer without rewriting either source.

    Args:
        tmp_path: Independent source and download directory.
        mocker: Framework patch for the Hub download.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    content = _content()
    original = _pointer(content)
    paths.your_library.write_text(original)
    downloaded = tmp_path / "downloaded.json"
    downloaded.write_bytes(content)
    download = mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download",
        return_value=str(downloaded),
    )
    artists = _storage(paths).export_artists(paths)
    assert [artist.spotify_id for artist in artists] == ["export"]
    assert paths.your_library.read_text() == original
    assert downloaded.read_bytes() == content
    download.assert_called_once_with(
        repo_id="owner/app",
        filename="spotify_manager/files/YourLibrary.json",
        repo_type="space",
        token="secret",
    )


def test_valid_local_export_does_not_consult_the_hub(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Keep valid source reads local even when recovery is configured.

    Args:
        tmp_path: Independent source directory.
        mocker: Framework patch recording unexpected downloads.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    paths.your_library.write_bytes(_content())
    download = mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download"
    )
    assert len(_storage(paths).export_artists(paths)) == 1
    download.assert_not_called()


@pytest.mark.parametrize(
    "payload", ["corrupt JSON", "{}", "version https://git-lfs.github.com/spec/v1\n"]
)
def test_ordinary_corruption_is_not_replaced_by_a_remote_snapshot(
    tmp_path: Path, mocker: MockerFixture, payload: str
) -> None:
    """Preserve corrupt input and reject an unrelated remote replacement.

    Args:
        tmp_path: Independent source directory.
        mocker: Framework patch recording unexpected downloads.
        payload: Invalid JSON, schema, or incomplete pointer.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    paths.your_library.write_text(payload)
    download = mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download"
    )
    with pytest.raises(LibrarySyncError):
        _storage(paths).export(paths)
    assert paths.your_library.read_text() == payload
    download.assert_not_called()


def test_custom_source_path_cannot_resolve_to_the_packaged_export(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Keep custom source paths outside the configured recovery boundary.

    Args:
        tmp_path: Independent source directory.
        mocker: Framework patch recording unexpected downloads.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    paths.your_library.write_text(_pointer(_content()))
    storage = AnalysisStorage(SpaceLibraryExport(tmp_path / "other.json", "owner/app"))
    download = mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download"
    )
    with pytest.raises(LibrarySyncError, match="Could not read valid JSON"):
        storage.export(paths)
    download.assert_not_called()


@pytest.mark.parametrize("downloaded", [b"different size", b" " * len(_content())])
def test_downloaded_bytes_must_match_the_packaged_content_identity(
    tmp_path: Path, mocker: MockerFixture, downloaded: bytes
) -> None:
    """Reject truncated or substituted bytes before export validation.

    Args:
        tmp_path: Independent source and download directory.
        mocker: Framework patch for the Hub download.
        downloaded: Wrong-size or wrong-digest source bytes.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    paths.your_library.write_text(_pointer(_content()))
    cached = tmp_path / "cached.json"
    cached.write_bytes(downloaded)
    mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download",
        return_value=str(cached),
    )
    with pytest.raises(LibrarySyncError, match="does not match"):
        _storage(paths).export(paths)
    assert paths.your_library.read_text() == _pointer(_content())


def test_matching_digest_does_not_bypass_export_schema_validation(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Reject an invalid export even when its content identity matches.

    Args:
        tmp_path: Independent source and download directory.
        mocker: Framework patch for the Hub download.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    paths.your_library.write_text(_pointer(b"{}"))
    cached = tmp_path / "cached.json"
    cached.write_bytes(b"{}")
    mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download",
        return_value=str(cached),
    )
    with pytest.raises(LibrarySyncError, match="export is invalid") as failure:
        _storage(paths).export(paths)
    assert isinstance(failure.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    "failure",
    [
        ConnectError("offline"),
        HfHubHTTPError(
            "unavailable",
            response=Response(503, request=Request("GET", "https://huggingface.co")),
        ),
        LocalEntryNotFoundError("missing"),
    ],
)
def test_hub_failures_preserve_the_original_source(
    tmp_path: Path, mocker: MockerFixture, failure: Exception
) -> None:
    """Translate transport failures without replacing the source.

    Args:
        tmp_path: Independent source directory.
        mocker: Framework patch for the Hub download.
        failure: Concrete external transport or missing-file exception.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    paths.your_library.write_text(_pointer(_content()))
    mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download",
        side_effect=failure,
    )
    with pytest.raises(LibrarySyncError, match="Could not resolve") as error:
        _storage(paths).export(paths)
    assert error.value.__cause__ is failure
    assert paths.your_library.read_text() == _pointer(_content())


def test_unreadable_download_is_an_explicit_export_failure(
    tmp_path: Path, mocker: MockerFixture
) -> None:
    """Retain filesystem errors as the explicit recovery failure cause.

    Args:
        tmp_path: Independent source directory and unreadable download path.
        mocker: Framework patch for the Hub download.
    """
    paths = LibraryAnalysisPaths.for_files_dir(tmp_path, "mirrors")
    paths.your_library.write_text(_pointer(_content()))
    mocker.patch(
        "spotify_manager.infrastructure.space_library_export.hf_hub_download",
        return_value=str(tmp_path),
    )
    with pytest.raises(LibrarySyncError, match="Could not resolve") as failure:
        _storage(paths).export(paths)
    assert isinstance(failure.value.__cause__, OSError)


def test_pointer_recognition_accepts_windows_line_endings() -> None:
    """Recognize complete CRLF pointers and reject unrelated failure causes."""
    text = _pointer(_content()).replace("\n", "\r\n")
    failure = LibrarySyncError("invalid JSON")
    failure.__cause__ = json.JSONDecodeError("invalid", text, 0)
    pointer = export_pointer(failure)
    assert pointer is not None
    assert pointer.sha256 == hashlib.sha256(_content()).hexdigest()
    assert pointer.size == len(_content())
    assert export_pointer(LibrarySyncError("not a JSON decode failure")) is None


@pytest.mark.parametrize(
    ("environment", "token"),
    [
        ({"SPACE_ID": "owner/app"}, None),
        ({"SPACE_ID": "owner/app", "HF_TOKEN": "hub"}, "hub"),
        (
            {
                "SPACE_ID": "owner/app",
                "SPOTIFY_MANAGER_STATE_TOKEN": "state",
                "HF_TOKEN": "hub",
            },
            "state",
        ),
        (
            {
                "SPACE_ID": "owner/app",
                "SPOTIFY_MANAGER_DATA_TOKEN": "data",
                "SPOTIFY_MANAGER_STATE_TOKEN": "state",
            },
            "data",
        ),
    ],
)
def test_bootstrap_scopes_recovery_to_the_space_and_existing_credentials(
    environment: dict[str, str], token: str | None
) -> None:
    """Retain credential precedence without exposing tokens in representations.

    Args:
        environment: Synthetic Space identity and credential aliases.
        token: Expected selected credential.
    """
    recovery = configured_export_recovery(environment)
    assert recovery is not None
    assert recovery.repo_id == "owner/app"
    assert recovery.path.name == "YourLibrary.json"
    assert recovery.token == token
    assert "token=" not in repr(recovery)


def test_local_bootstrap_keeps_export_reads_offline() -> None:
    """Keep local execution offline even when a Hub credential is available."""
    assert configured_export_recovery({"HF_TOKEN": "secret"}) is None
