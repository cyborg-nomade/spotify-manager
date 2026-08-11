"""Tests for the HF library-file upload CLI command."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def upload_plan() -> main.hf_upload.LibraryFilesUploadPlan:
    """Return a small validated plan for CLI tests."""
    return main.hf_upload.LibraryFilesUploadPlan(
        repo_id="owner/space",
        revision="main",
        resources=(
            main.hf_upload.UploadResource(
                name="YourLibrary.json",
                local_path=Path("/tmp/YourLibrary.json"),
                path_in_repo="spotify_manager/files/YourLibrary.json",
                item_count=12,
                size_bytes=1024,
            ),
        ),
    )


def test_upload_command_dry_run_does_not_call_hf(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def prepare(**kwargs: object) -> main.hf_upload.LibraryFilesUploadPlan:
        received.update(kwargs)
        return upload_plan()

    monkeypatch.setattr(main.hf_upload, "prepare_library_files_upload", prepare)
    monkeypatch.setattr(
        main.hf_upload,
        "upload_library_files",
        lambda *_args, **_kwargs: pytest.fail("dry run called HF"),
    )

    result = CliRunner().invoke(
        main.app,
        ["upload-library-files-to-hf", "--your-library-only", "--dry-run"],
    )

    assert result.exit_code == 0
    assert received["include_your_library"] is True
    assert received["include_lastfm"] is False
    assert "Dry run complete" in result.output
    assert "YourLibrary.json" in result.output


def test_upload_command_rejects_conflicting_file_options() -> None:
    result = CliRunner().invoke(
        main.app,
        [
            "upload-library-files-to-hf",
            "--your-library-only",
            "--lastfm-only",
        ],
    )

    assert result.exit_code != 0
    assert "either --your-library-only or --lastfm-only" in result.output


def test_upload_command_prints_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main.hf_upload,
        "prepare_library_files_upload",
        lambda **_kwargs: upload_plan(),
    )
    monkeypatch.setattr(
        main.hf_upload,
        "upload_library_files",
        lambda _plan: main.hf_upload.LibraryFilesUploadResult(
            commit_url="https://huggingface.co/spaces/owner/space/commit/1",
            uploaded_files=1,
            deleted_stale_parts=0,
            upload_size_bytes=1024,
        ),
    )

    result = CliRunner().invoke(
        main.app,
        ["upload-library-files-to-hf", "--your-library-only"],
    )

    assert result.exit_code == 0
    assert "Uploaded 1 files" in result.output
    assert "spaces/owner/space/commit/1" in result.output


def test_upload_command_reports_inline_parts_and_removes_stale_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = main.hf_upload.LibraryFilesUploadPlan(
        repo_id="owner/space",
        revision="main",
        resources=upload_plan().resources,
        lastfm_parts=(
            main.hf_upload.GeneratedPart(
                Path("part-aa"),
                "spotify_manager/files/part-aa",
                b"abc",
            ),
            main.hf_upload.GeneratedPart(
                Path("part-ab"),
                "spotify_manager/files/part-ab",
                b"def",
            ),
        ),
    )
    monkeypatch.setattr(
        main.hf_upload,
        "prepare_library_files_upload",
        lambda **_kwargs: plan,
    )
    monkeypatch.setattr(
        main.hf_upload,
        "upload_library_files",
        lambda _plan: main.hf_upload.LibraryFilesUploadResult(
            commit_url="https://huggingface.co/commit/1",
            uploaded_files=3,
            deleted_stale_parts=2,
            upload_size_bytes=2048,
        ),
    )

    result = CliRunner().invoke(main.app, ["upload-library-files-to-hf"])

    assert result.exit_code == 0
    assert "2 inline" in result.output
    assert "Removed 2 obsolete fallback parts" in result.output


@pytest.mark.parametrize("stage", ["prepare", "upload"])
def test_upload_command_reports_validation_and_upload_errors(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    def fail(*_args, **_kwargs):
        raise main.hf_upload.LibraryFilesUploadError(f"{stage} failed")

    monkeypatch.setattr(
        main.hf_upload,
        "prepare_library_files_upload",
        fail if stage == "prepare" else lambda **_kwargs: upload_plan(),
    )
    monkeypatch.setattr(
        main.hf_upload,
        "upload_library_files",
        fail if stage == "upload" else lambda _plan: pytest.fail("unexpected upload"),
    )

    result = CliRunner().invoke(main.app, ["upload-library-files-to-hf"])

    assert result.exit_code == 1
    assert f"{stage} failed" in result.output
