"""Decode original dormant-artist liked and popularity observations."""

from dataclasses import replace

from spotify_manager.application.dormant_values import BlastFromPastArtistsError
from spotify_manager.domain.discovery import CatalogTrack


def liked_statuses(
    response: object, batch: tuple[CatalogTrack, ...]
) -> dict[str, bool]:
    """Retain exact list cardinality and original truthiness for liked responses.

    Args:
        response: Original SDK response.
        batch: Original ordered request batch.

    Returns:
        Original last-observed statuses by track identity.

    Raises:
        BlastFromPastArtistsError: Response is not a list matching the batch length.
    """
    if not isinstance(response, list) or len(response) != len(batch):
        raise BlastFromPastArtistsError(
            "Spotify returned invalid Liked Songs statuses."
        )
    statuses = {}
    for track, liked in zip(batch, response, strict=True):
        statuses[track.spotify_id] = bool(liked)
    return statuses


def popularity_details(
    response: object, by_id: dict[str, CatalogTrack]
) -> tuple[CatalogTrack, ...]:
    """Retain original response order, coercion and duplicate detail observations.

    Args:
        response: Original SDK response.
        by_id: Original last-observed source tracks by identity.

    Returns:
        Original populated details, including integer boolean popularity tolerance.

    Raises:
        BlastFromPastArtistsError: Original response lacks its details list.
    """
    rows = response.get("tracks") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise BlastFromPastArtistsError("Spotify returned invalid liked-track details.")
    details = []
    for row in rows:
        detail = _detail(row, by_id)
        if detail is not None:
            details.append(detail)
    return tuple(details)


def _detail(row: object, by_id: dict[str, CatalogTrack]) -> CatalogTrack | None:
    if not isinstance(row, dict):
        return None
    source = by_id.get(str(row.get("id") or "").strip())
    if source is None:
        return None
    popularity = row.get("popularity")
    return replace(
        source, popularity=popularity if isinstance(popularity, int) else None
    )
