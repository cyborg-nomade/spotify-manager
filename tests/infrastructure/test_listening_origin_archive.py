"""Verify checkpoint schema and private dataset compare-and-swap behavior."""

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from huggingface_hub import CommitOperationAdd
from huggingface_hub.errors import HfHubHTTPError

from spotify_manager.application.listening_origin_ports import OriginCacheError
from spotify_manager.infrastructure.huggingface import listening_origin_archive
from spotify_manager.infrastructure.huggingface.listening_origin_archive import PATH
from spotify_manager.infrastructure.huggingface.listening_origin_archive import (
    HubOriginArchive,
)
from spotify_manager.infrastructure.huggingface.listening_origin_archive import _encode
from spotify_manager.infrastructure.huggingface.listening_origin_archive import _load
from tests.support.listening_origins import origin_metadata


class FixtureDataset:
    """Simulate a competing dataset commit while the archive writes."""

    def __init__(self, path: Path) -> None:
        """Bind the simulated data files."""
        self.path = path
        self.head = "before"
        self.private = True
        self.parents: list[str] = []
        self.revisions: list[str] = []

    def repo_info(self, dataset: str, *, repo_type: str) -> SimpleNamespace:
        """Report the current simulated dataset HEAD and privacy setting."""
        assert dataset == "fixture/library" and repo_type == "dataset"
        return SimpleNamespace(private=self.private, sha=self.head)

    def download(
        self, dataset: str, filename: str, *, revision: str, repo_type: str, token: str
    ) -> str:
        """Read only the exact revision the archive has pinned."""
        assert (dataset, filename, repo_type, token) == (
            "fixture/library",
            PATH,
            "dataset",
            "test-token",
        )
        self.revisions.append(revision)
        return str(self.path / revision)

    def create_commit(
        self,
        dataset: str,
        *,
        repo_type: str,
        parent_commit: str,
        operations: list[CommitOperationAdd],
        commit_message: str,
    ) -> None:
        """Reject the initial parent and then store the merged sidecar."""
        assert dataset == "fixture/library" and repo_type == "dataset"
        assert commit_message == "Checkpoint Artist Map country evidence"
        self.parents.append(parent_commit)
        if parent_commit == "before":
            self.head = "concurrent"
            request = httpx.Request("POST", "https://hub.invalid")
            response = httpx.Response(412, request=request)
            raise HfHubHTTPError("Revision changed", response=response)
        (operation,) = operations
        assert operation.path_in_repo == PATH
        assert isinstance(operation.path_or_fileobj, bytes)
        (self.path / "after").write_bytes(operation.path_or_fileobj)
        self.head = "after"


@pytest.mark.asyncio
async def test_archive_rebases_and_preserves_a_newer_concurrent_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Commit only the sidecar and retain the evidence published by another writer."""
    dataset = FixtureDataset(tmp_path)
    archive = HubOriginArchive("fixture/library", "test-token")
    monkeypatch.setattr(archive, "_api", dataset)
    monkeypatch.setattr(listening_origin_archive, "hf_hub_download", dataset.download)
    alpha = origin_metadata("Alpha")
    beta = origin_metadata("Beta", ("AU",))
    newer = origin_metadata("Alpha", ("CA",), fetched_at="2026-11-22T00:00:00+00:00")
    (tmp_path / "before").write_bytes(_encode((alpha,)))
    (tmp_path / "concurrent").write_bytes(_encode((newer,)))
    committed = await archive.checkpoint((alpha, beta))
    assert set(committed) == {newer, beta}
    assert dataset.parents == ["before", "concurrent"]
    assert await archive.restore() == committed
    assert dataset.revisions == ["before", "concurrent", "after"]
    assert _load(tmp_path / "after") == committed


@pytest.mark.asyncio
async def test_archive_refuses_to_read_a_public_dataset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Safeguard private-origin archive data at the concrete repository boundary."""
    dataset = FixtureDataset(tmp_path)
    dataset.private = False
    archive = HubOriginArchive("fixture/library", "test-token")
    monkeypatch.setattr(archive, "_api", dataset)
    with pytest.raises(OriginCacheError, match="private dataset"):
        await archive.restore()
    assert not dataset.revisions
