import json

import pytest

from spotify_manager.core.library_data import LibraryDataConflictError
from spotify_manager.core.library_data import LibraryDataDocumentError
from spotify_manager.core.library_data import LibraryDataIntegrityError
from spotify_manager.core.library_data import LibraryDataService
from spotify_manager.core.library_data.models import ArtifactMetadata
from spotify_manager.core.library_data.models import LibraryDataSnapshot
from spotify_manager.core.library_data.models import new_manifest
from spotify_manager.core.library_data.models import with_artifact
from spotify_manager.infrastructure.persistence import JsonLibraryDataStore


def paths(tmp_path):
    return {
        "albums": tmp_path / "working" / "albums_total_new.json",
        "tracks": tmp_path / "working" / "liked_tracks_total.json",
        "artists": tmp_path / "working" / "artists_total.json",
        "scrobbles": tmp_path / "working" / "lastfmstats-man-et-arms.json",
    }


def service(tmp_path, working_paths=None):
    return LibraryDataService(
        JsonLibraryDataStore(tmp_path / "store"),
        working_paths or paths(tmp_path),
    )


def test_publish_and_hydrate_all_artifact_shapes(tmp_path):
    working = paths(tmp_path)
    working["albums"].parent.mkdir(parents=True)
    working["albums"].write_text('[{"spotify_id":"album"}]')
    working["tracks"].write_text('[{"spotify_id":"track"}]')
    working["artists"].write_text('[{"spotify_id":"artist"}]')
    working["scrobbles"].write_text('{"scrobbles":[]}')
    writer = service(tmp_path, working)

    for name in ("albums", "tracks", "artists", "scrobbles"):
        writer.publish(name, source="test")

    restored_paths = {
        name: tmp_path / "restored" / path.name for name, path in working.items()
    }
    reader = service(tmp_path, restored_paths)
    statuses = reader.hydrate_all()

    assert all(status.local_current for status in statuses)
    assert json.loads(restored_paths["albums"].read_text())[0]["spotify_id"] == "album"
    assert json.loads(restored_paths["scrobbles"].read_text()) == {"scrobbles": []}


def test_publish_rejects_wrong_top_level_shape(tmp_path):
    working = paths(tmp_path)
    working["albums"].parent.mkdir(parents=True)
    working["albums"].write_text('{"albums":[]}')

    with pytest.raises(LibraryDataDocumentError, match="must contain a list"):
        service(tmp_path, working).publish("albums", source="test")


def test_same_artifact_conflict_is_rejected(tmp_path):
    first_paths = paths(tmp_path)
    second_paths = {
        name: tmp_path / "second" / path.name for name, path in first_paths.items()
    }
    first_paths["albums"].parent.mkdir(parents=True)
    first_paths["albums"].write_text("[]")
    first = service(tmp_path, first_paths)
    first.publish("albums", source="seed")

    second = service(tmp_path, second_paths)
    second.hydrate("albums")
    first.hydrate("albums")
    first_paths["albums"].write_text('[{"spotify_id":"newer"}]')
    first.publish("albums", source="first")
    second_paths["albums"].write_text('[{"spotify_id":"stale"}]')

    with pytest.raises(LibraryDataConflictError, match="changed in another process"):
        second.publish("albums", source="second")


def test_different_artifact_writes_merge(tmp_path):
    working = paths(tmp_path)
    working["albums"].parent.mkdir(parents=True)
    working["albums"].write_text("[]")
    working["tracks"].write_text("[]")
    data = service(tmp_path, working)

    data.publish("albums", source="album refresh")
    data.publish("tracks", source="track refresh")

    manifest = data.snapshot().document
    assert set(manifest["artifacts"]) == {"albums", "tracks"}


def test_status_reports_local_drift(tmp_path):
    working = paths(tmp_path)
    working["artists"].parent.mkdir(parents=True)
    working["artists"].write_text("[]")
    data = service(tmp_path, working)
    data.publish("artists", source="artist refresh")
    working["artists"].write_text('[{"spotify_id":"local-only"}]')

    status = next(item for item in data.statuses() if item.name == "artists")

    assert status.exists is True
    assert status.local_current is False
    assert status.source == "artist refresh"


def test_service_requires_every_managed_path(tmp_path):
    with pytest.raises(ValueError, match="Missing library-data paths"):
        LibraryDataService(JsonLibraryDataStore(tmp_path / "store"), {})  # type: ignore[arg-type]


def test_hydrate_rejects_corrupt_restored_payload(tmp_path):
    metadata = ArtifactMetadata(
        filename="albums_total_new.json",
        blob_path="artifacts/albums_total_new.json.gz",
        sha256="0" * 64,
        size_bytes=2,
        updated_at="2026-08-24T12:00:00+00:00",
        source="test",
    )

    class CorruptStore:
        def read(self):
            return LibraryDataSnapshot(
                with_artifact(new_manifest(), "albums", metadata),
                "revision",
            )

        def restore(self, _name, _metadata, *, revision, destination):
            destination.write_bytes(b"corrupt")

    with pytest.raises(LibraryDataIntegrityError, match="wrong size"):
        LibraryDataService(CorruptStore(), paths(tmp_path)).hydrate("albums")  # type: ignore[arg-type]


def test_publish_rejects_missing_working_file(tmp_path):
    with pytest.raises(LibraryDataIntegrityError, match="Could not read"):
        service(tmp_path).publish("tracks", source="test")
