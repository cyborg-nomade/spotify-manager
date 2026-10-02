"""Original tolerant lookup response parsing without new boundary validation."""

from typing import cast

from spotify_manager.application.lookup_effects import LookupPage
from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.lookup_values import SpotifyLookupResponseError


def artist_identity(raw: object) -> tuple[str, str] | None:
    """Read the original trimmed artist identity from a raw object.

    Args:
        raw: Original unvalidated SDK response.

    Returns:
        Original complete identity or none for an incomplete response.
    """
    if not isinstance(raw, dict):
        return None
    identifier = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    return (identifier, name) if identifier and name else None


def primary_artist_id(raw: object) -> str | None:
    """Read only the original first credited artist identity.

    Args:
        raw: Original unvalidated SDK row.

    Returns:
        Original trimmed identity or none.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("artists"), list):
        return None
    artists = raw["artists"]
    if not artists or not isinstance(artists[0], dict):
        return None
    return str(artists[0].get("id") or "").strip() or None


def primary_artist_name(raw: dict[str, object], *, trim: bool = True) -> str | None:
    """Read the original optional first artist display name.

    Args:
        raw: Original unvalidated object.
        trim: Original display trimming flag; ambiguity retains raw spacing.

    Returns:
        Original first name or none without a first object credit.
    """
    artists = raw.get("artists")
    if not isinstance(artists, list) or not artists or not isinstance(artists[0], dict):
        return None
    name = str(artists[0].get("name") or "")
    return name.strip() if trim else name


def page(raw: object, error: str) -> LookupPage:
    """Validate the original page container while retaining every raw row.

    Args:
        raw: Original SDK page.
        error: Original shape error message.

    Returns:
        Original raw rows and unvalidated continuation value.

    Raises:
        SpotifyLookupResponseError: The original container or items is invalid.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise SpotifyLookupResponseError(error)
    return LookupPage(raw["items"], raw.get("next"))


def search_items(raw: object, resource: str, message: str) -> list[object]:
    """Retain original search container checks without validating candidate rows.

    Args:
        raw: Original search response.
        resource: Original plural response key.
        message: Original shape error message.

    Returns:
        Every original candidate row in order.

    Raises:
        SpotifyLookupResponseError: Original items are not an array.
    """
    container = raw.get(resource) if isinstance(raw, dict) else None
    items = container.get("items") if isinstance(container, dict) else None
    if not isinstance(items, list):
        raise SpotifyLookupResponseError(message)
    return items


def album_batch(raw: object) -> list[object]:
    """Retain original batched-album container validation.

    Args:
        raw: Original SDK response.

    Returns:
        Every original raw album row.

    Raises:
        SpotifyLookupResponseError: Original albums are not an array.
    """
    albums = raw.get("albums") if isinstance(raw, dict) else None
    if not isinstance(albums, list):
        raise SpotifyLookupResponseError("Spotify returned invalid batched album data.")
    return albums


def minimized_track(raw: dict[str, object], album_id: str) -> LookupTrack:
    """Retain original required display fields and unchecked track identity.

    Args:
        raw: Original track object.
        album_id: Original requested album identity.

    Returns:
        Original minimized cache record.

    Raises:
        SpotifyLookupResponseError: Original name or URI is empty.
    """
    name = str(raw.get("name") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not name or not uri:
        raise SpotifyLookupResponseError(
            f"Spotify returned incomplete track data for album {album_id!r}."
        )
    return {"id": cast(str | None, raw.get("id")), "name": name, "uri": uri}


def track(raw: object) -> ResolvedTrack | None:
    """Retain original optional track metadata and integer-only popularity.

    Args:
        raw: Original unvalidated SDK response.

    Returns:
        Original complete minimized identity or none.
    """
    if not isinstance(raw, dict):
        return None
    identifier = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    artists = raw.get("artists")
    if not isinstance(artists, list) or not artists or not isinstance(artists[0], dict):
        return None
    artist = str(artists[0].get("name") or "").strip()
    album = _optional_album_name(raw.get("album"))
    popularity = raw.get("popularity")
    if not identifier or not name or not artist:
        return None
    return ResolvedTrack(
        identifier,
        name,
        artist,
        album,
        popularity if isinstance(popularity, int) else 0,
    )


def _optional_album_name(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None
    return str(raw.get("name") or "").strip() or None


def artist_identities(rows: list[object]) -> list[tuple[str, str]]:
    """Minimize valid original artist candidates without deduplication.

    Args:
        rows: Original search candidates.

    Returns:
        Complete identities in original encounter order.
    """
    result = []
    for row in rows:
        identity = artist_identity(row)
        if identity is not None:
            result.append(identity)
    return result


def track_identities(rows: list[object]) -> list[ResolvedTrack]:
    """Minimize valid original track candidates without choosing among them.

    Args:
        rows: Original search candidates.

    Returns:
        Complete identities in original encounter order.
    """
    result = []
    for row in rows:
        identity = track(row)
        if identity is not None:
            result.append(identity)
    return result


def live_album(
    raw: dict[str, object], fallback_id: str | None = None
) -> LiveAlbumCandidate:
    """Retain distinct original matching, final and ambiguity display facts.

    Args:
        raw: Original album object.
        fallback_id: Original requested identity when the response ID is falsey.

    Returns:
        Original candidate before final completeness validation.
    """
    identifier = str(raw.get("id") or fallback_id or "").strip()
    name = str(raw.get("name") or "")
    primary = primary_artist_name(raw)
    display = primary_artist_name(raw, trim=False)
    return LiveAlbumCandidate(identifier, name, primary, display or "")


def live_albums(rows: list[object]) -> list[LiveAlbumCandidate]:
    """Minimize original object candidates without applying exact-match decisions.

    Args:
        rows: Original ordered unchecked search rows.

    Returns:
        Original object observations in encounter order.
    """
    result = []
    for row in rows:
        if isinstance(row, dict):
            result.append(live_album(row))
    return result
