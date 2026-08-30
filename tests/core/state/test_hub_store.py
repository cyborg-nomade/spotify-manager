"""Contracts for the private Hugging Face state adapter."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from huggingface_hub.errors import HfHubHTTPError
from huggingface_hub.errors import EntryNotFoundError
from requests import Response

from spotify_manager.core.state import StateConflictError
from spotify_manager.core.state import StateConfigurationError
from spotify_manager.core.state.models import new_document
from spotify_manager.infrastructure.huggingface import state_store
from spotify_manager.infrastructure.huggingface.state_store import HubStateStore


class FakeApi:
    """Small HfApi stand-in recording revision-guarded commits."""

    def __init__(self) -> None:
        self.commit_kwargs: dict[str, object] | None = None
        self.error: Exception | None = None
        self.revision: str | None = "repo-revision"

    def repo_info(self, *_args, **_kwargs):
        return SimpleNamespace(sha=self.revision)

    def create_commit(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.commit_kwargs = kwargs
        return SimpleNamespace(oid="saved-revision")


def test_hub_store_reads_an_immutable_revision_and_commits_with_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state.json"
    document = new_document()
    path.write_text(json.dumps(document), encoding="utf-8")
    downloaded: dict[str, object] = {}

    def download(**kwargs):
        downloaded.update(kwargs)
        return str(path)

    monkeypatch.setattr(state_store, "hf_hub_download", download)
    api = FakeApi()
    store = HubStateStore("owner/state", token="token", api=api)  # type: ignore[arg-type]

    read = store.read()
    saved = store.write(
        read.document,
        expected_revision=read.revision,
        message="checkpoint",
    )

    assert downloaded["revision"] == "repo-revision"
    assert read.revision == "repo-revision"
    assert saved.revision == "saved-revision"
    assert api.commit_kwargs is not None
    assert api.commit_kwargs["parent_commit"] == "repo-revision"
    assert api.commit_kwargs["commit_message"] == "checkpoint"


def test_hub_store_translates_parent_conflict() -> None:
    response = Response()
    response.status_code = 409
    api = FakeApi()
    api.error = HfHubHTTPError("conflict", response=response)
    store = HubStateStore("owner/state", api=api)  # type: ignore[arg-type]

    with pytest.raises(StateConflictError, match="Hugging Face"):
        store.write(
            new_document(),
            expected_revision="old-revision",
            message="conflicting write",
        )


def test_hub_store_explains_commit_rate_limits() -> None:
    response = Response()
    response.status_code = 429
    api = FakeApi()
    api.error = HfHubHTTPError("rate limited", response=response)
    store = HubStateStore("owner/state", api=api)  # type: ignore[arg-type]

    with pytest.raises(StateConfigurationError, match="try again in about one hour"):
        store.write(
            new_document(),
            expected_revision="current-revision",
            message="checkpoint",
        )


def test_hub_store_rejects_repository_without_revision() -> None:
    api = FakeApi()
    api.revision = None
    store = HubStateStore("owner/state", api=api)  # type: ignore[arg-type]

    with pytest.raises(StateConfigurationError, match="no readable revision"):
        store.read()


def test_hub_store_starts_empty_when_state_file_is_missing(monkeypatch) -> None:
    def missing(**_kwargs):
        raise EntryNotFoundError("missing")

    monkeypatch.setattr(state_store, "hf_hub_download", missing)

    snapshot = HubStateStore("owner/state", api=FakeApi()).read()  # type: ignore[arg-type]

    assert snapshot.revision == "repo-revision"
    assert snapshot.document["namespaces"] == {}
