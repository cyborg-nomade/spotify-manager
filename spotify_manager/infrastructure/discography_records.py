"""Parse original Spotify catalog facts without importing routine business helpers."""

from spotify_manager.application.discography_catalog import DiscographyPage
from spotify_manager.application.discography_values import DiscographyError
from spotify_manager.domain.discography_catalog import (
    COMPILATION_PATTERN as COMPILATION_PATTERN,
)
from spotify_manager.domain.discography_catalog import LIVE_PATTERN as LIVE_PATTERN
from spotify_manager.domain.discography_catalog import catalog_type
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.releases import edition_details
from spotify_manager.domain.releases import release_identity
from spotify_manager.infrastructure.studio_records import artist_pairs
from spotify_manager.infrastructure.studio_records import studio_release


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
