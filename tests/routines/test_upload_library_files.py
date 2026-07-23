"""Tests for uploading refreshed library exports to Hugging Face."""

import base64
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

from huggingface_hub import CommitOperationAdd
from huggingface_hub import CommitOperationDelete

from spotify_manager.routines import upload_library_files


class FakeHfApi:
    """Capture HF operations without making network requests."""

    def __init__(self, remote_files: list[str] | None = None) -> None:
        self.remote_files = remote_files or []
        self.operations: list[CommitOperationAdd | CommitOperationDelete] = []
        self.commit_message = ""

    def list_repo_files(self, **_kwargs: object) -> list[str]:
        return self.remote_files

    def create_commit(
        self,
        *,
        operations: list[CommitOperationAdd | CommitOperationDelete],
        commit_message: str,
        **_kwargs: object,
    ) -> SimpleNamespace:
        self.operations = operations
        self.commit_message = commit_message
        return SimpleNamespace(
            commit_url="https://huggingface.co/spaces/example/commit/1"
        )


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_prepare_lastfm_upload_builds_round_trippable_deterministic_parts(
    tmp_path: Path,
) -> None:
    payload = {
        "username": "listener",
        "scrobbles": [
            {"artist": "Artist", "track": f"Track {index}"} for index in range(20)
        ],
    }
    source = tmp_path / upload_library_files.LASTFM_FILENAME
    write_json(source, payload)

    first_plan = upload_library_files.prepare_library_files_upload(
        include_your_library=False,
        files_dir=tmp_path,
    )
    second_plan = upload_library_files.prepare_library_files_upload(
        include_your_library=False,
        files_dir=tmp_path,
    )

    first_content = b"".join(part.content for part in first_plan.lastfm_parts)
    second_content = b"".join(part.content for part in second_plan.lastfm_parts)
    restored = gzip.decompress(base64.b64decode(first_content))

    assert restored == source.read_bytes()
    assert first_content == second_content
    assert first_plan.resources[0].item_count == 20
    assert first_plan.lastfm_parts[0].local_path.name.endswith("part-aa")


def test_upload_materializes_parts_and_deletes_stale_local_and_remote_parts(
    tmp_path: Path,
) -> None:
    source = tmp_path / upload_library_files.LASTFM_FILENAME
    write_json(source, {"scrobbles": [{"artist": "Artist", "track": "Track"}]})
    stale_local = tmp_path / f"{upload_library_files.LASTFM_PART_PREFIX}zz"
    stale_local.write_text("stale", encoding="ascii")
    stale_binary_local = (
        tmp_path / f"{upload_library_files.LASTFM_BINARY_PART_PREFIX}aa"
    )
    stale_binary_local.write_bytes(b"stale")
    stale_remote = (
        f"{upload_library_files.REMOTE_FILES_DIR}/"
        f"{upload_library_files.LASTFM_PART_PREFIX}zz"
    )
    stale_binary_remote = (
        f"{upload_library_files.REMOTE_FILES_DIR}/"
        f"{upload_library_files.LASTFM_BINARY_PART_PREFIX}aa"
    )
    api = FakeHfApi(remote_files=[stale_remote, stale_binary_remote])
    plan = upload_library_files.prepare_library_files_upload(
        include_your_library=False,
        files_dir=tmp_path,
    )

    result = upload_library_files.upload_library_files(plan, api=api)  # type: ignore[arg-type]

    added_paths = {
        operation.path_in_repo
        for operation in api.operations
        if isinstance(operation, CommitOperationAdd)
    }
    deleted_paths = {
        operation.path_in_repo
        for operation in api.operations
        if isinstance(operation, CommitOperationDelete)
    }
    assert not stale_local.exists()
    assert not stale_binary_local.exists()
    assert all(
        part.local_path.read_bytes() == part.content for part in plan.lastfm_parts
    )
    assert {resource.path_in_repo for resource in plan.resources} <= added_paths
    assert {part.path_in_repo for part in plan.lastfm_parts} <= added_paths
    assert deleted_paths == {stale_remote, stale_binary_remote}
    assert result.deleted_stale_parts == 2
    assert result.uploaded_files == 1 + len(plan.lastfm_parts)


def test_your_library_only_does_not_generate_lastfm_parts(tmp_path: Path) -> None:
    write_json(
        tmp_path / upload_library_files.YOUR_LIBRARY_FILENAME,
        {"tracks": [{"artist": "Artist", "track": "Track"}]},
    )

    plan = upload_library_files.prepare_library_files_upload(
        include_lastfm=False,
        files_dir=tmp_path,
    )

    assert [resource.name for resource in plan.resources] == [
        upload_library_files.YOUR_LIBRARY_FILENAME
    ]
    assert plan.lastfm_parts == ()


def test_invalid_export_is_rejected_before_upload(tmp_path: Path) -> None:
    source = tmp_path / upload_library_files.YOUR_LIBRARY_FILENAME
    source.write_text("not json", encoding="utf-8")

    try:
        upload_library_files.prepare_library_files_upload(
            include_lastfm=False,
            files_dir=tmp_path,
        )
    except upload_library_files.LibraryFilesUploadError as exc:
        assert "not valid JSON" in str(exc)
    else:
        raise AssertionError("invalid JSON should fail validation")
