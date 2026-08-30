"""Hugging Face dataset implementation of the central state store."""

from __future__ import annotations

import json
from typing import Any

from httpx import HTTPError as HttpxError
from huggingface_hub import CommitOperationAdd
from huggingface_hub import HfApi
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import EntryNotFoundError
from huggingface_hub.errors import HfHubHTTPError
from huggingface_hub.errors import LocalEntryNotFoundError
from huggingface_hub.errors import RepositoryNotFoundError

from spotify_manager.core.state.models import StateConfigurationError
from spotify_manager.core.state.models import StateConflictError
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import StateSnapshot
from spotify_manager.core.state.models import new_document
from spotify_manager.core.state.models import validate_document


class HubStateStore:
    """Store shared state as one versioned file in a private HF dataset."""

    def __init__(
        self,
        repo_id: str,
        *,
        filename: str = "state.json",
        token: str | bool | None = None,
        api: HfApi | None = None,
    ) -> None:
        """Configure the private dataset and its single state filename."""
        self.repo_id = repo_id
        self.filename = filename
        self.token = token
        self.api = api or HfApi(token=token)

    def _repo_revision(self) -> str:
        try:
            revision = self.api.repo_info(
                self.repo_id,
                repo_type="dataset",
                token=self.token,
            ).sha
        except RepositoryNotFoundError as exc:
            raise StateConfigurationError(
                f"State dataset {self.repo_id!r} does not exist or is inaccessible."
            ) from exc
        except (HfHubHTTPError, HttpxError) as exc:
            raise StateConfigurationError(
                f"Could not reach state dataset {self.repo_id!r}."
            ) from exc
        if not revision:
            raise StateConfigurationError(
                f"State dataset {self.repo_id!r} has no readable revision."
            )
        return revision

    def read(self) -> StateSnapshot:
        """Read state at an immutable dataset revision."""
        revision = self._repo_revision()
        try:
            path = hf_hub_download(
                repo_id=self.repo_id,
                filename=self.filename,
                repo_type="dataset",
                revision=revision,
                token=self.token,
            )
        except EntryNotFoundError:
            return StateSnapshot(new_document(), revision)
        except (HfHubHTTPError, LocalEntryNotFoundError, HttpxError) as exc:
            raise StateConfigurationError(
                f"Could not download shared state from {self.repo_id!r}."
            ) from exc
        try:
            with open(path, encoding="utf-8") as handle:
                raw: Any = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateDocumentError(
                f"Shared state in {self.repo_id!r} is invalid."
            ) from exc
        return StateSnapshot(validate_document(raw), revision)

    def write(
        self,
        document: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> StateSnapshot:
        """Commit one guarded replacement without rebuilding the Space."""
        validated = validate_document(document)
        payload = (
            json.dumps(validated, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        ).encode()
        try:
            commit = self.api.create_commit(
                repo_id=self.repo_id,
                repo_type="dataset",
                revision="main",
                parent_commit=expected_revision,
                operations=[
                    CommitOperationAdd(
                        path_in_repo=self.filename,
                        path_or_fileobj=payload,
                    )
                ],
                commit_message=message,
                token=self.token,
            )
        except HfHubHTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {409, 412}:
                raise StateConflictError(
                    "Shared state changed before the Hugging Face commit completed."
                ) from exc
            if status == 429:
                raise StateConfigurationError(
                    "The Hugging Face shared-state commit limit was reached. "
                    "Durable progress through the previous checkpoint was preserved; "
                    "try again in about one hour."
                ) from exc
            raise StateConfigurationError(
                f"Could not write shared state to {self.repo_id!r}."
            ) from exc
        except HttpxError as exc:
            raise StateConfigurationError(
                f"Could not reach state dataset {self.repo_id!r} for writing."
            ) from exc
        return StateSnapshot(validated, commit.oid)
