import gzip
import json
from types import SimpleNamespace

import pytest
from huggingface_hub.errors import EntryNotFoundError
from huggingface_hub.errors import HfHubHTTPError
from requests import Response

from spotify_manager.core.library_data import LibraryDataConflictError
from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import new_manifest
from spotify_manager.core.library_data.models import with_artifact
from spotify_manager.infrastructure.huggingface import library_data_store
from spotify_manager.infrastructure.huggingface.library_data_store import (
    HubLibraryDataStore,
)


class FakeApi:
    def __init__(self):
        self.revision = "repo-revision"
        self.error = None
        self.commit_kwargs = None

    def repo_info(self, *_args, **_kwargs):
        return SimpleNamespace(sha=self.revision)

    def create_commit(self, **kwargs):
        if self.error:
            raise self.error
        self.commit_kwargs = kwargs
        return SimpleNamespace(oid="saved-revision")


def metadata():
    return ArtifactMetadata(
        filename="albums_total_new.json",
        blob_path="artifacts/albums_total_new.json.gz",
        sha256="0" * 64,
        size_bytes=2,
        updated_at="2026-08-24T12:00:00+00:00",
        source="test",
    )


def test_hub_data_store_reads_and_commits_two_files(tmp_path, monkeypatch):
    manifest = with_artifact(new_manifest(), "albums", metadata())
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    def download(**_kwargs):
        return str(manifest_path)

    monkeypatch.setattr(library_data_store, "hf_hub_download", download)
    api = FakeApi()
    store = HubLibraryDataStore("owner/data", token="token", api=api)

    snapshot = store.read()
    saved = store.write(
        "albums",
        b"[]",
        snapshot.document,
        expected_revision=snapshot.revision,
        message="publish albums",
    )

    assert saved.revision == "saved-revision"
    assert api.commit_kwargs["parent_commit"] == "repo-revision"
    operations = api.commit_kwargs["operations"]
    assert [operation.path_in_repo for operation in operations] == [
        "artifacts/albums_total_new.json.gz",
        "manifest.json",
    ]
    assert gzip.decompress(operations[0].path_or_fileobj) == b"[]"


def test_hub_data_store_restores_pinned_blob(tmp_path, monkeypatch):
    compressed = tmp_path / "artifact.gz"
    compressed.write_bytes(gzip.compress(b"[]"))
    requested = {}

    def download(**kwargs):
        requested.update(kwargs)
        return str(compressed)

    monkeypatch.setattr(library_data_store, "hf_hub_download", download)
    destination = tmp_path / "restored.json"
    HubLibraryDataStore("owner/data", api=FakeApi()).restore(
        "albums",
        metadata(),
        revision="pinned",
        destination=destination,
    )

    assert destination.read_bytes() == b"[]"
    assert requested["revision"] == "pinned"


def test_hub_data_store_translates_parent_conflict():
    response = Response()
    response.status_code = 409
    api = FakeApi()
    api.error = HfHubHTTPError("conflict", response=response)
    manifest = with_artifact(new_manifest(), "albums", metadata())

    with pytest.raises(LibraryDataConflictError, match="Hugging Face"):
        HubLibraryDataStore("owner/data", api=api).write(
            "albums",
            b"[]",
            manifest,
            expected_revision="old",
            message="conflict",
        )


def test_hub_data_store_starts_empty_without_manifest(monkeypatch):
    monkeypatch.setattr(
        library_data_store,
        "hf_hub_download",
        lambda **_kwargs: (_ for _ in ()).throw(EntryNotFoundError("missing")),
    )

    snapshot = HubLibraryDataStore("owner/data", api=FakeApi()).read()

    assert snapshot.document["artifacts"] == {}


def test_hub_data_store_rejects_repository_without_revision():
    api = FakeApi()
    api.revision = None

    with pytest.raises(Exception, match="no readable revision"):
        HubLibraryDataStore("owner/data", api=api).read()
