"""Compatibility seams for original duplicate-preserving album comparisons."""

from typing import cast

from spotify_manager.application.legacy_library_conversion import compare_ids
from spotify_manager.application.legacy_library_effects import Comparison
from spotify_manager.application.legacy_library_effects import ComparisonAlbum
from spotify_manager.client import get_spotipy_client as get_spotipy_client
from spotify_manager.models.file_items import SimplifiedAlbum
from spotify_manager.models.your_library import YourLibraryFile


def get_album_id_list_from_your_library_file(
    your_library_file: YourLibraryFile,
) -> list[str]:
    """Read original export identities without deduplication.

    Args:
        your_library_file: Original export authority.

    Returns:
        Album identities in original encounter order.
    """
    return [album.spotify_id for album in your_library_file.albums]


def get_album_id_list_from_total_albums_file(
    total_albums_file: list[SimplifiedAlbum],
) -> list[str]:
    """Read original legacy identities without deduplication.

    Args:
        total_albums_file: Original legacy authority.

    Returns:
        Album identities in original encounter order.
    """
    return [album.spotify_id for album in total_albums_file]


def enrich_id_to_album_dict(album_id: str) -> ComparisonAlbum:
    """Retain original per-identity client construction and first-credit display.

    Args:
        album_id: Original requested identity.

    Returns:
        Original unchecked metadata with requested identity retained.
    """
    print(album_id)
    sp = get_spotipy_client()
    album = sp.album(album_id)
    print(album["name"])
    return cast(
        ComparisonAlbum,
        {"name": album["name"], "artist": album["artists"][0]["name"], "id": album_id},
    )


def compare_and_get_dict(
    your_library_id_list: list[str], total_albums_id_list: list[str]
) -> Comparison:
    """Enrich original additions before removals, including duplicate requests.

    Args:
        your_library_id_list: Original export identities.
        total_albums_id_list: Original legacy identities.

    Returns:
        Original complete comparison mapping.
    """
    return compare_ids(
        your_library_id_list, total_albums_id_list, enrich_id_to_album_dict, print
    )
