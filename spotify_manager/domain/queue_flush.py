"""Queue flush source selection and live membership policies."""

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack


def daily_sources(
    tracks: tuple[PlaylistTrack, ...], limit: int
) -> tuple[PlaylistTrack, ...]:
    """Retain the first marker of each primary artist up to the original limit.

    Args:
        tracks: Original live Queue in source order.
        limit: Original configured distinct-artist limit.

    Returns:
        Original ordered first-primary-artist markers.
    """
    selected: list[PlaylistTrack] = []
    seen: set[str] = set()
    for track in tracks:
        if track.primary_artist_id in seen:
            continue
        seen.add(track.primary_artist_id)
        selected.append(track)
        if len(selected) == limit:
            break
    return tuple(selected)


def source_uris(tracks: tuple[PlaylistTrack, ...], source: PlaylistTrack) -> list[str]:
    """Retain live source markers or the original stored source fallback.

    Args:
        tracks: Original initial live Queue observations.
        source: Original authoritative source marker.

    Returns:
        Original ordered matching URIs, or the stored marker's URI.
    """
    uris: list[str] = []
    for track in tracks:
        if track.primary_artist_id == source.primary_artist_id:
            uris.append(track.uri)
    return uris or [source.uri]


def removable_sources(
    uris: list[str],
    live: set[str],
    action: str,
    target: CatalogTrack | None,
) -> list[str]:
    """Retain original live sources while protecting an advance target's URI.

    Args:
        uris: Original decoded source URIs, including duplicates.
        live: Original current live URI set.
        action: Original plan action, including unknown legacy values.
        target: Original optional target marker.

    Returns:
        Original ordered removable URIs.
    """
    removable: list[str] = []
    for uri in uris:
        if uri not in live:
            continue
        if action == "advance" and target is not None and uri == target.uri:
            continue
        removable.append(uri)
    return removable


def remove_membership(
    tracks: tuple[PlaylistTrack, ...],
    uris: list[str],
    live_ids: set[str],
    live_uris: set[str],
) -> None:
    """Update original local membership only after accepted source removal.

    Args:
        tracks: Initial live observations, excluding subsequently added targets.
        uris: Original accepted or proposed removals.
        live_ids: Caller-owned original distinct track identities.
        live_uris: Caller-owned original distinct track URIs.
    """
    for uri in uris:
        live_uris.discard(uri)
        matching = _first_uri_id(tracks, uri)
        if matching is not None:
            live_ids.discard(matching)


def _first_uri_id(tracks: tuple[PlaylistTrack, ...], uri: str) -> str | None:
    for track in tracks:
        if track.uri == uri:
            return track.spotify_id
    return None
