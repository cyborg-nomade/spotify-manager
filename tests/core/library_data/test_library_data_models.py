import pytest

from spotify_manager.core.library_data import LibraryDataDocumentError
from spotify_manager.core.library_data.models import validate_artifact_payload
from spotify_manager.core.library_data.models import validate_manifest


def test_artifact_payload_must_be_valid_json():
    with pytest.raises(LibraryDataDocumentError, match="is not valid JSON"):
        validate_artifact_payload("tracks", b"not-json")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("filename", "wrong.json", "must use filename"),
        ("sha256", "not-a-checksum", "invalid checksum"),
        ("size_bytes", -1, "invalid size"),
    ],
)
def test_manifest_rejects_invalid_artifact_metadata(field, value, message):
    metadata = {
        "filename": "albums_total_new.json",
        "blob_path": "artifacts/albums_total_new.json.gz",
        "sha256": "0" * 64,
        "size_bytes": 2,
        "updated_at": "2026-08-24T12:00:00+00:00",
        "source": "test",
    }
    metadata[field] = value

    with pytest.raises(LibraryDataDocumentError, match=message):
        validate_manifest(
            {
                "schema_version": 1,
                "created_at": "2026-08-24T12:00:00+00:00",
                "updated_at": "2026-08-24T12:00:00+00:00",
                "artifacts": {"albums": metadata},
            }
        )
