"""Parse original Palace album search rows and first playable markers."""

from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.domain.palace_values import CatalogAlbum
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack


def artist_names(raw_album: dict[str, object]) -> tuple[str, ...]:
    """Parse original ordered artist display names without trimming or validation.

    Args:
        raw_album: Original raw album row.

    Returns:
        Original nonempty artist names after string coercion.
    """
    raw = raw_album.get("artists")
    if not isinstance(raw, list):
        return ()
    result = []
    for artist in raw:
        if isinstance(artist, dict) and artist.get("name"):
            result.append(str(artist["name"]))
    return tuple(result)


def album_search(response: object, title: str) -> tuple[CatalogAlbum, ...]:
    """Validate original album search paging and retain complete raw-order facts.

    Args:
        response: Original raw search payload.
        title: Original expected title used in error text.

    Returns:
        Complete original observations with raw one-based search positions.

    Raises:
        PalaceOfMemoryDataError: Original response has no usable albums items list.
    """
    page = response.get("albums") if isinstance(response, dict) else None
    rows = page.get("items") if isinstance(page, dict) else None
    if not isinstance(rows, list):
        raise PalaceOfMemoryDataError(
            f"Spotify returned invalid search data for {title}."
        )
    result = []
    for rank, raw in enumerate(rows, start=1):
        album = _album(raw, rank)
        if album is not None:
            result.append(album)
    return tuple(result)


def _album(raw: object, rank: int) -> CatalogAlbum | None:
    if not isinstance(raw, dict):
        return None
    identity = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    artists = artist_names(raw)
    if not identity or not uri or not name or not artists:
        return None
    return CatalogAlbum(identity, uri, name, artists, rank)


def first_track(response: object, album: SpotifyAlbum) -> SpotifyFirstTrack:
    """Select the original first complete marker without reordering or paging ahead.

    Args:
        response: Original raw first-page track response.
        album: Original resolved release used for error context.

    Returns:
        Original first complete playable marker.

    Raises:
        PalaceOfMemoryDataError: Original tracks are malformed or have no marker.
    """
    rows = response.get("items") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise PalaceOfMemoryDataError(
            f"Spotify returned invalid tracks for {album.artist} - {album.album}."
        )
    for raw in rows:
        track = _track(raw)
        if track is not None:
            return track
    raise PalaceOfMemoryDataError(
        f"No playable first track found for {album.artist} - {album.album}."
    )


def _track(raw: object) -> SpotifyFirstTrack | None:
    if not isinstance(raw, dict):
        return None
    identity = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not identity or not uri or not name:
        return None
    return SpotifyFirstTrack(identity, uri, name)
