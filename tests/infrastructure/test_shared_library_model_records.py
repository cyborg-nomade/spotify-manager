"""Protect shared tolerant saved-album conversion and newest-value identity records."""

import pytest

from spotify_manager.infrastructure.library_models import album_from_saved_item
from spotify_manager.infrastructure.library_models import deduplicate_models
from spotify_manager.models.your_library import YourLibraryAlbum


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"album": None},
        {"album": {}},
        {"album": {"id": "one", "name": "Release"}},
        {"album": {"id": "one", "name": "Release", "artists": []}},
        {"album": {"id": "one", "name": "Release", "artists": [None]}},
        {"album": {"id": "one", "name": "Release", "artists": [{}]}},
    ],
)
def test_shared_saved_album_skips_original_unusable_rows(raw: object) -> None:
    """Retain original malformed saved-row tolerance without partial models.

    Args:
        raw: Original unusable live row.
    """
    assert album_from_saved_item(raw) is None


@pytest.mark.parametrize("uri", [None, "spotify:album:custom"])
def test_shared_saved_album_coerces_original_fields_and_falls_back_to_identity(
    uri: str | None,
) -> None:
    """Retain primary-credit string coercion and the original missing-URI fallback.

    Args:
        uri: Original optional raw URI.
    """
    raw = {
        "album": {
            "id": 5,
            "name": 7,
            "uri": uri,
            "artists": [{"name": 9}, {"name": "Other"}],
        }
    }
    assert album_from_saved_item(raw) == YourLibraryAlbum(
        artist="9", album="7", uri=uri or "spotify:album:5"
    )


def test_shared_model_identity_keeps_newest_value_in_first_identity_order() -> None:
    """Retain replacement value, first insertion order and falsey-identity exclusion."""
    first = YourLibraryAlbum(artist="Artist", album="Old", uri="spotify:album:one")
    other = YourLibraryAlbum(artist="Other", album="Other", uri="spotify:album:two")
    latest = YourLibraryAlbum(artist="Artist", album="New", uri="spotify:album:one")
    empty = YourLibraryAlbum(artist="Empty", album="Empty", uri="spotify:album:")
    assert deduplicate_models((first, other, latest, empty)) == [latest, other]
    assert deduplicate_models(()) == []
