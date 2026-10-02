"""Original permissive Spotify album and track conversion at the SDK boundary."""

from operator import itemgetter
from typing import Any

from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.utils.sorting import get_ordering_string


def album(payload: Any) -> SimplifiedAlbum:
    """Convert original unchecked metadata using only its first artist credit.

    Args:
        payload: Permissive SDK boundary; native indexing errors are retained.

    Returns:
        Original simplified album model.
    """
    return SimplifiedAlbum(
        spotify_id=payload["id"],
        name=payload["name"],
        artist=SimplifiedArtist(
            spotify_id=payload["artists"][0]["id"], name=payload["artists"][0]["name"]
        ),
        ordering_string=get_ordering_string(payload["name"]),
    )


def saved_albums(rows: list[Any]) -> list[SimplifiedAlbum]:
    """Parse truthy original saved-album rows without new validation.

    Args:
        rows: Permissive original SDK rows.

    Returns:
        Converted models in raw encounter order.
    """
    result: list[SimplifiedAlbum] = []
    for row in rows:
        if row and row["album"]:
            result.append(album(row["album"]))
    return result


def track_rows(rows: list[Any]) -> list[dict[str, object]]:
    """Retain original integer coercion before track sorting.

    Args:
        rows: Original unchecked track rows.

    Returns:
        Original truthy rows converted to sortable fields.
    """
    result: list[dict[str, object]] = []
    for row in rows:
        if row:
            result.append(
                {
                    "disc_number": int(row["disc_number"]),
                    "track_number": int(row["track_number"]),
                    "uri": row["uri"],
                }
            )
    return result


def sort_tracks(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    """Sort coerced tracks stably by disc and track number.

    Args:
        rows: Original unvalidated sortable fields.

    Returns:
        Original playback order.
    """
    return sorted(rows, key=itemgetter("disc_number", "track_number"))


def validate_tracks(rows: list[dict[str, object]]) -> list[SimplifiedTrack]:
    """Validate tracks after the original ordering message.

    Args:
        rows: Original ordered fields.

    Returns:
        Original simplified track models.
    """
    result = []
    for row in rows:
        result.append(SimplifiedTrack.model_validate(row))
    return result
