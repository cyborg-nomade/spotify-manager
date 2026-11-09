"""Published snapshots stay independent of sync writes and failed preparations."""

from dataclasses import replace
from pathlib import Path
from typing import Literal

import pytest

from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import ArtifactName
from spotify_manager.core.library_data.models import LibraryDataConfigurationError
from spotify_manager.core.library_data.models import LibraryDataConflictError
from spotify_manager.core.library_data.models import LibraryDataDocumentError
from spotify_manager.core.library_data.models import LibraryDataIntegrityError
from spotify_manager.core.library_data.models import payload_sha256
from spotify_manager.core.library_data.models import with_artifact
from spotify_manager.infrastructure.persistence.json_library_data_store import (
    JsonLibraryDataStore,
)
from tests.support.scrobble_downloads import HISTORY
from tests.support.scrobble_downloads import NEW_HISTORY
from tests.support.scrobble_downloads import download_fixture
from tests.support.scrobble_downloads import publish_history


class PublishingStore(JsonLibraryDataStore):
    """Publish a real replacement between the first manifest read and restore.

    Args:
        root: Test-owned durable store directory.
    """

    def __init__(self, root: Path) -> None:
        """Start with a single pending concurrent publication.

        Args:
            root: Independent compressed artifact directory.
        """
        super().__init__(root)
        self.restores = 0

    def restore(
        self,
        name: ArtifactName,
        metadata: ArtifactMetadata,
        *,
        revision: str,
        destination: Path,
    ) -> None:
        """Simulate another publisher winning after the consumer pins a revision.

        Args:
            name: Artifact selected by the consumer.
            metadata: Original pinned metadata.
            revision: Original manifest revision.
            destination: Consumer-owned destination.
        """
        self.restores += 1
        if self.restores == 1:
            self._replace_history(metadata)
        super().restore(name, metadata, revision=revision, destination=destination)

    def _replace_history(self, metadata: ArtifactMetadata) -> None:
        current = self.read()
        updated = replace(
            metadata, sha256=payload_sha256(NEW_HISTORY), size_bytes=len(NEW_HISTORY)
        )
        self.write(
            "scrobbles",
            NEW_HISTORY,
            with_artifact(current.document, "scrobbles", updated),
            expected_revision=current.revision,
            message="concurrent publication",
        )


class RestoreFaultStore(JsonLibraryDataStore):
    """Fail only the external restore boundary, retaining a real manifest.

    Args:
        root: Test-owned durable store directory.
        fault: Specific failure or integrity violation to simulate.
    """

    def __init__(
        self,
        root: Path,
        fault: Literal["size", "hash", "missing", "conflict", "offline"],
    ) -> None:
        """Configure one concrete fault.

        Args:
            root: Independent artifact directory.
            fault: Restore outcome, without replacing application execution.
        """
        super().__init__(root)
        self.fault = fault
        self.restores = 0

    def restore(
        self,
        name: ArtifactName,
        metadata: ArtifactMetadata,
        *,
        revision: str,
        destination: Path,
    ) -> None:
        """Return a corrupt result or propagate an existing storage failure.

        Args:
            name: Requested artifact.
            metadata: Original expected size and digest.
            revision: Original pinned manifest.
            destination: Request-owned destination.

        Raises:
            LibraryDataConflictError: Every restore races with publication.
            LibraryDataConfigurationError: Storage is unavailable.
        """
        self.restores += 1
        if self.fault == "conflict":
            raise LibraryDataConflictError("publisher won")
        if self.fault == "offline":
            raise LibraryDataConfigurationError("offline")
        if self.fault == "size":
            destination.write_bytes(b"{}")
        if self.fault == "hash":
            destination.write_bytes(b"x" * metadata.size_bytes)


def test_unpublished_working_edits_cannot_change_downloaded_bytes(
    tmp_path: Path,
) -> None:
    """An in-progress or dirty working export is never a download source.

    Args:
        tmp_path: Isolated canonical and download storage.
    """
    fixture = download_fixture(tmp_path)
    publish_history(fixture)
    revision = fixture.service.snapshot().revision
    fixture.working.write_bytes(b"incomplete working file")
    snapshot = fixture.files.prepare()
    assert snapshot is not None and snapshot.path.read_bytes() == HISTORY
    assert snapshot.metadata.sha256 == payload_sha256(HISTORY)
    assert snapshot.metadata.size_bytes == len(HISTORY)
    assert fixture.service.snapshot().revision == revision
    assert fixture.working.read_bytes() == b"incomplete working file"
    snapshot.close()


def test_download_still_works_without_a_local_working_file(tmp_path: Path) -> None:
    """The published artifact remains authoritative after a process loses its cache.

    Args:
        tmp_path: Isolated canonical and download storage.
    """
    fixture = download_fixture(tmp_path)
    publish_history(fixture)
    fixture.working.unlink()
    snapshot = fixture.files.prepare()
    assert snapshot is not None and snapshot.path.read_bytes() == HISTORY
    assert not fixture.working.exists()
    snapshot.close()


def test_publication_during_download_keeps_each_snapshot_complete(
    tmp_path: Path,
) -> None:
    """A new publication and another download cannot overwrite the first file.

    Args:
        tmp_path: Independent mutable working file and immutable download spools.
    """
    fixture = download_fixture(tmp_path)
    publish_history(fixture)
    first = fixture.files.prepare()
    assert first is not None
    publish_history(fixture, NEW_HISTORY)
    second = fixture.files.prepare()
    assert second is not None and second.path != first.path
    assert (
        first.path.read_bytes() == HISTORY and second.path.read_bytes() == NEW_HISTORY
    )
    first.close()
    first.close()
    assert not first.path.exists() and second.path.exists()
    second.close()
    assert not list(fixture.spool.iterdir())


def test_interleaved_local_publication_retries_a_fresh_manifest(tmp_path: Path) -> None:
    """A local revision conflict acquires the new complete bytes on its next try.

    Args:
        tmp_path: Test-owned durable store.
    """
    store = PublishingStore(tmp_path / "durable")
    fixture = download_fixture(tmp_path, store)
    publish_history(fixture)
    snapshot = fixture.files.prepare()
    assert snapshot is not None and snapshot.path.read_bytes() == NEW_HISTORY
    assert snapshot.metadata.sha256 == payload_sha256(NEW_HISTORY)
    assert store.restores == 2
    snapshot.close()


@pytest.mark.parametrize("fault", ["size", "hash", "missing"])
def test_failed_integrity_preparation_removes_all_temporary_files(
    tmp_path: Path, fault: Literal["size", "hash", "missing"]
) -> None:
    """An incomplete or corrupt preparation never escapes as an attachment.

    Args:
        tmp_path: Independent store and spool.
        fault: Wrong size, wrong checksum or absent restored file.
    """
    fixture = download_fixture(tmp_path, RestoreFaultStore(tmp_path / "durable", fault))
    publish_history(fixture)
    with pytest.raises(LibraryDataIntegrityError):
        fixture.files.prepare()
    assert not list(fixture.spool.iterdir())


@pytest.mark.parametrize("fault", ["conflict", "offline"])
def test_failed_storage_preparation_is_bounded_and_cleans_up(
    tmp_path: Path, fault: Literal["conflict", "offline"]
) -> None:
    """Persistent storage failures cannot leak spools or retry forever.

    Args:
        tmp_path: Independent store and spool.
        fault: Repeated publication conflicts or unavailable storage.
    """
    store = RestoreFaultStore(tmp_path / "durable", fault)
    fixture = download_fixture(tmp_path, store)
    publish_history(fixture)
    error = (
        LibraryDataConflictError
        if fault == "conflict"
        else LibraryDataConfigurationError
    )
    with pytest.raises(error):
        fixture.files.prepare()
    assert store.restores == (3 if fault == "conflict" else 1)
    assert not list(fixture.spool.iterdir())


def test_invalid_manifest_cleans_up_without_hydrating_or_publishing(
    tmp_path: Path,
) -> None:
    """A damaged manifest does not make the working file a download fallback.

    Args:
        tmp_path: Independent canonical storage.
    """
    fixture = download_fixture(tmp_path)
    publish_history(fixture)
    fixture.store.manifest_path.write_text("{}")
    with pytest.raises(LibraryDataDocumentError):
        fixture.files.prepare()
    assert not list(fixture.spool.iterdir())
