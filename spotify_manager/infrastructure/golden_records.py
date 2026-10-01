"""Parse Golden Oldies catalog facts with the original tolerant boundary rules."""

from collections.abc import Iterator

from spotify_manager.application.something_old_values import SomethingOldSpotifyError
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate


def positive_int(raw: object) -> int | None:
    """Parse the original nonnegative integer, excluding booleans.

    Args:
        raw: Original raw Spotify value.

    Returns:
        Original usable integer or none.
    """
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    return None


def artist_record(raw: object, rank: int) -> SpotifyArtistCandidate | None:
    """Parse one complete original artist search row.

    Args:
        raw: Original raw catalog row.
        rank: Original one-based search position.

    Returns:
        Complete original candidate or none for an incomplete row.
    """
    if not isinstance(raw, dict):
        return None
    identity = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not identity or not name or not uri:
        return None
    followers = raw.get("followers")
    total = (
        positive_int(followers.get("total")) if isinstance(followers, dict) else None
    )
    return SpotifyArtistCandidate(
        identity, name, uri, positive_int(raw.get("popularity")), total, rank
    )


def artist_search(response: object, name: str) -> tuple[SpotifyArtistCandidate, ...]:
    """Validate original artist paging and retain all complete rows in search order.

    Args:
        response: Original raw search response.
        name: Original expected artist spelling for errors.

    Returns:
        Complete original candidates without applying matching policy.

    Raises:
        SomethingOldSpotifyError: Original response lacks a usable items list.
    """
    page = response.get("artists") if isinstance(response, dict) else None
    items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(items, list):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid artist search data for {name}."
        )
    result = []
    for rank, raw in enumerate(items, start=1):
        candidate = artist_record(raw, rank)
        if candidate is not None:
            result.append(candidate)
    return tuple(result)


def track_artist_data(raw: object) -> tuple[tuple[str, str], ...]:
    """Parse original ordered credits, retaining their untrimmed labels.

    Args:
        raw: Original raw artist array.

    Returns:
        Complete original identity/name pairs.
    """
    if not isinstance(raw, list):
        return ()
    result = []
    for item in raw:
        if isinstance(item, dict) and item.get("id") and item.get("name"):
            result.append((str(item["id"]), str(item["name"])))
    return tuple(result)


def popular_track(raw: object, artist: SpotifyArtistCandidate) -> SelectedTrack | None:
    """Parse an original popular marker credited to any position of the artist.

    Args:
        raw: Original raw track row.
        artist: Original accepted artist mapping.

    Returns:
        Original complete marker or none for unusable or unrelated facts.
    """
    if not isinstance(raw, dict):
        return None
    identity = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    artists = track_artist_data(raw.get("artists"))
    if not identity or not uri or not name:
        return None
    if artist.spotify_id not in {identity for identity, _name in artists}:
        return None
    raw_album = raw.get("album")
    album = (
        str(raw_album.get("name") or "").strip() if isinstance(raw_album, dict) else ""
    )
    return SelectedTrack(
        identity,
        uri,
        name,
        album,
        tuple(name for _identity, name in artists),
        "Spotify popular tracks",
    )


def popular_tracks(
    response: object, artist: SpotifyArtistCandidate
) -> Iterator[SelectedTrack]:
    """Validate original top-track data and parse usable facts in response order.

    Args:
        response: Original raw top-track response.
        artist: Original accepted artist mapping.

    Returns:
        Lazy original complete markers, including duplicate identities.

    Raises:
        SomethingOldSpotifyError: Original response has no tracks list.
    """
    rows = response.get("tracks") if isinstance(response, dict) else None
    if not isinstance(rows, list):
        raise SomethingOldSpotifyError(
            f"Spotify returned invalid top tracks for {artist.name}."
        )
    return _popular_rows(rows, artist)


def _popular_rows(
    rows: list[object], artist: SpotifyArtistCandidate
) -> Iterator[SelectedTrack]:
    for raw in rows:
        track = popular_track(raw, artist)
        if track is not None:
            yield track
