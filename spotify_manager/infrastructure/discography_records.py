"""Parse original Spotify catalog facts without importing routine business helpers."""

from dataclasses import replace

from spotify_manager.application.discography_catalog import DiscographyPage
from spotify_manager.application.discography_values import DiscographyAlbumError
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.domain.discography_catalog import (
    COMPILATION_PATTERN as COMPILATION_PATTERN,
)
from spotify_manager.domain.discography_catalog import LIVE_PATTERN as LIVE_PATTERN
from spotify_manager.domain.discography_catalog import catalog_type
from spotify_manager.domain.discography_links import ReviewRelease
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.releases import edition_details
from spotify_manager.domain.releases import release_identity
from spotify_manager.infrastructure.studio_records import artist_pairs
from spotify_manager.infrastructure.studio_records import studio_release


def linked_release(raw: object, identity: str) -> ReviewRelease:
    """Parse an explicit edition without fetched-catalog artist/type filters.

    Args:
        raw: Spotify's exact album response.
        identity: Requested validated album identity.

    Returns:
        Exact edition and actual credits, including singles or other artists.

    Raises:
        DiscographyAlbumError: Metadata is invalid or availability restricted.
    """
    if not isinstance(raw, dict) or raw.get("id") != identity:
        raise DiscographyAlbumError("Spotify returned no matching album metadata.")
    artists = artist_pairs(raw.get("artists"))
    name, total = raw.get("name"), raw.get("total_tracks")
    if not artists or not isinstance(name, str) or not name.strip():
        raise DiscographyAlbumError("Spotify returned incomplete album metadata.")
    if type(total) is not int or total <= 0:
        raise DiscographyAlbumError("This album has no available tracks.")
    if raw.get("is_playable") is False or raw.get("restrictions"):
        raise DiscographyAlbumError(
            "This album is unavailable in this account's market."
        )
    album_type = raw.get("album_type")
    if not isinstance(album_type, str) or album_type not in {
        "album",
        "single",
        "compilation",
        "ep",
    }:
        raise DiscographyAlbumError("Spotify returned an invalid album type.")
    standard = studio_release(raw, artists[0][0])
    kind = _kind(raw, name, total, standard.release_type if standard else None)
    release = _record(raw, identity, name.strip(), total, kind or "Single", False)
    release = replace(release, uri=f"spotify:album:{identity}")
    return ReviewRelease(release, tuple(name for _, name in artists), True)


def positive_int(value: object) -> int:
    """Retain original Discography integer tolerance, including positive booleans.

    Args:
        value: Original untrusted track-count field.

    Returns:
        Original positive integer or zero.
    """
    return value if isinstance(value, int) and value > 0 else 0


def catalog_release(raw: object, artist_id: str) -> CatalogRelease | None:
    """Parse original primary-credit studio and optional non-studio releases.

    Args:
        raw: Original untrusted Spotify release record.
        artist_id: Original expected first artist identity.

    Returns:
        Complete original usable candidate or none.
    """
    if not isinstance(raw, dict):
        return None
    artists = artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    identity = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or identity).strip()
    if not identity or not name:
        return None
    total = positive_int(raw.get("total_tracks"))
    standard = studio_release(raw, artist_id)
    kind = _kind(raw, name, total, standard.release_type if standard else None)
    if kind is None:
        return None
    return _record(raw, identity, name, total, kind, standard is not None)


def _kind(
    raw: dict[str, object], name: str, total: int, standard: str | None
) -> str | None:
    return catalog_type(
        str(raw.get("album_type") or "").casefold(),
        str(raw.get("album_group") or "").casefold(),
        name,
        total,
        standard,
    )


def _record(
    raw: dict[str, object],
    identity: str,
    name: str,
    total: int,
    kind: str,
    standard: bool,
) -> CatalogRelease:
    uri = str(raw.get("uri") or f"spotify:album:{identity}").strip()
    release_date = str(raw.get("release_date") or "Unknown")
    _, rank = edition_details(name)
    return CatalogRelease(
        identity,
        uri,
        name,
        kind,
        release_date,
        release_date,
        total,
        release_identity(name),
        False,
        rank == 0,
        rank,
        standard,
    )


def catalog_page(raw: object, artist_id: str) -> DiscographyPage:
    """Validate original page shape while retaining raw-row pagination authority.

    Args:
        raw: Original untrusted page.
        artist_id: Original expected primary artist.

    Returns:
        Usable releases and original raw accounting.

    Raises:
        DiscographyError: The original page or items container is invalid.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise DiscographyError("Spotify returned invalid artist releases.")
    releases = []
    for item in raw["items"]:
        parsed = catalog_release(item, artist_id)
        if parsed is not None:
            releases.append(parsed)
    return DiscographyPage(tuple(releases), len(raw["items"]), bool(raw.get("next")))


def saved_statuses(raw: object, count: int) -> list[bool]:
    """Validate original exact batch length before applying truthiness conversion.

    Args:
        raw: Original untrusted saved-status response.
        count: Original requested batch size.

    Returns:
        Original ordered truthiness-based membership.

    Raises:
        DiscographyError: The original response container or length is invalid.
    """
    if not isinstance(raw, list) or len(raw) != count:
        raise DiscographyError("Spotify returned invalid saved-album statuses.")
    return [bool(value) for value in raw]
