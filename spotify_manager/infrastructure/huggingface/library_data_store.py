"""Hugging Face dataset adapter for durable canonical library files."""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path
from typing import Any

from httpx import HTTPError as HttpxError
from huggingface_hub import CommitOperationAdd
from huggingface_hub import HfApi
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import EntryNotFoundError
from huggingface_hub.errors import HfHubHTTPError
from huggingface_hub.errors import LocalEntryNotFoundError
from huggingface_hub.errors import RepositoryNotFoundError

from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataConfigurationError
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.core.library_data.models import LibraryDataDocumentError
from spotify_manager.core.library_data.models import LibraryDataIntegrityError
from spotify_manager.core.library_data.models import LibraryDataSnapshot
from spotify_manager.core.library_data.models import manifest_bytes
from spotify_manager.core.library_data.models import new_manifest
from spotify_manager.core.library_data.models import validate_manifest


class HubLibraryDataStore:
    """Store compressed artifacts and one manifest in a private HF dataset."""

    def __init__(
        self,
        repo_id: str,
        *,
        manifest_filename: str = "manifest.json",
        token: str | bool | None = None,
        api: HfApi | None = None,
    ) -> None:
        """Configure the dataset and its manifest path."""
        self.repo_id = repo_id
        self.manifest_filename = manifest_filename
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
            raise LibraryDataConfigurationError(
                f"Library-data dataset {self.repo_id!r} does not exist "
                "or is inaccessible."
            ) from exc
        except (HfHubHTTPError, HttpxError) as exc:
            raise LibraryDataConfigurationError(
                f"Could not reach library-data dataset {self.repo_id!r}."
            ) from exc
        if not revision:
            raise LibraryDataConfigurationError(
                f"Library-data dataset {self.repo_id!r} has no readable revision."
            )
        return revision

    def read(self) -> LibraryDataSnapshot:
        """Read the manifest at one immutable dataset revision."""
        revision = self._repo_revision()
        try:
            path = hf_hub_download(
                repo_id=self.repo_id,
                filename=self.manifest_filename,
                repo_type="dataset",
                revision=revision,
                token=self.token,
            )
        except EntryNotFoundError:
            return LibraryDataSnapshot(new_manifest(), revision)
        except (HfHubHTTPError, LocalEntryNotFoundError, HttpxError) as exc:
            raise LibraryDataConfigurationError(
                f"Could not download the library-data manifest from {self.repo_id!r}."
            ) from exc
        try:
            with open(path, encoding="utf-8") as handle:
                raw: Any = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise LibraryDataDocumentError(
                f"Library-data manifest in {self.repo_id!r} is invalid."
            ) from exc
        return LibraryDataSnapshot(validate_manifest(raw), revision)

    def restore(
        self,
        name: ArtifactName,
        metadata: ArtifactMetadata,
        *,
        revision: str,
        destination: Path,
    ) -> None:
        """Download and decompress one artifact pinned to its manifest revision."""
        del name
        try:
            compressed_path = hf_hub_download(
                repo_id=self.repo_id,
                filename=metadata.blob_path,
                repo_type="dataset",
                revision=revision,
                token=self.token,
            )
            with (
                gzip.open(compressed_path, "rb") as source,
                destination.open("wb") as target,
            ):
                shutil.copyfileobj(source, target)
        except EntryNotFoundError as exc:
            raise LibraryDataIntegrityError(
                f"Durable blob for {metadata.filename} is missing."
            ) from exc
        except (
            OSError,
            EOFError,
            HfHubHTTPError,
            LocalEntryNotFoundError,
            HttpxError,
        ) as exc:
            raise LibraryDataConfigurationError(
                f"Could not restore {metadata.filename} from {self.repo_id!r}."
            ) from exc

    def write(
        self,
        name: ArtifactName,
        payload: bytes,
        manifest: dict[str, object],
        *,
        expected_revision: str,
        message: str,
    ) -> LibraryDataSnapshot:
        """Commit one compressed artifact and its manifest atomically."""
        validated = validate_manifest(manifest)
        metadata_raw = validated["artifacts"][name]
        metadata = ArtifactMetadata(
            filename=metadata_raw["filename"],
            blob_path=metadata_raw["blob_path"],
            sha256=metadata_raw["sha256"],
            size_bytes=metadata_raw["size_bytes"],
            updated_at=metadata_raw["updated_at"],
            source=metadata_raw["source"],
        )
        compressed = gzip.compress(payload, compresslevel=9, mtime=0)
        try:
            commit = self.api.create_commit(
                repo_id=self.repo_id,
                repo_type="dataset",
                revision="main",
                parent_commit=expected_revision,
                operations=[
                    CommitOperationAdd(
                        path_in_repo=metadata.blob_path,
                        path_or_fileobj=compressed,
                    ),
                    CommitOperationAdd(
                        path_in_repo=self.manifest_filename,
                        path_or_fileobj=manifest_bytes(validated),
                    ),
                ],
                commit_message=message,
                token=self.token,
            )
        except HfHubHTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in {409, 412}:
                raise LibraryDataConflictError(
                    "Library data changed before the Hugging Face commit completed."
                ) from exc
            raise LibraryDataConfigurationError(
                f"Could not write library data to {self.repo_id!r}."
            ) from exc
        except HttpxError as exc:
            raise LibraryDataConfigurationError(
                f"Could not reach {self.repo_id!r} while publishing library data."
            ) from exc
        return LibraryDataSnapshot(validated, commit.oid)
