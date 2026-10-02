"""Shared original permissive studio release boundary parsing."""

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.releases import edition_details
from spotify_manager.domain.releases import is_non_studio_title
from spotify_manager.domain.releases import release_identity
from spotify_manager.domain.releases import studio_release_type


def positive_int(raw: object, fallback: int = 0) -> int:
    """Parse a positive integer returned by Spotify.

    Args:
        raw: Original raw boundary.
        fallback: Original fallback boundary.

    Returns:
        Original complete compatible result.
    """
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw if raw > 0 else fallback
    if isinstance(raw, str):
        try:
            parsed = int(raw.strip())
        except ValueError:
            return fallback
        return parsed if parsed > 0 else fallback
    return fallback


def artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Return Spotify artist ids and names in credit order.

    Args:
        raw: Original raw boundary.

    Returns:
        Original complete compatible result.
    """
    if not isinstance(raw, list):
        return ()
    artists: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        spotify_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if spotify_id:
            artists.append((spotify_id, name or spotify_id))
    return tuple(artists)


def studio_release(
    raw: object,
    artist_id: str,
) -> DiscographyRelease | None:
    """Parse one primary-artist studio album or EP candidate.

    Args:
        raw: Original raw boundary.
        artist_id: Original artist id boundary.

    Returns:
        Original complete compatible result.
    """
    if not isinstance(raw, dict):
        return None
    artists = artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or spotify_id).strip()
    if not spotify_id or not uri or not name or is_non_studio_title(name):
        return None

    total_tracks = positive_int(raw.get("total_tracks"))
    raw_type = str(raw.get("album_type") or "").casefold()
    release_type = studio_release_type(raw_type, total_tracks, name)
    if release_type is None:
        return None
    return _studio_record(
        raw, artists[0], spotify_id, uri, name, total_tracks, release_type
    )


def _studio_record(
    raw: dict[str, object],
    artist: tuple[str, str],
    spotify_id: str,
    uri: str,
    name: str,
    total_tracks: int,
    release_type: str,
) -> DiscographyRelease:
    release_date = str(raw.get("release_date") or "Unknown")
    _base, edition_rank = edition_details(name)
    return DiscographyRelease(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        release_type=release_type,
        release_date=release_date,
        chronology_date=release_date,
        total_tracks=total_tracks,
        primary_artist_id=artist[0],
        primary_artist_name=artist[1],
        identity=release_identity(name),
        saved=False,
        plain=edition_rank == 0,
        edition_rank=edition_rank,
    )
