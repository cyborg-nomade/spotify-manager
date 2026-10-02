"""Preserve first primary artist spelling and ordered unique marker grouping."""

from collections import defaultdict

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import MarkerQueueName
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discography_values import QueueName


def marker_groups(
    tracks: tuple[PlaylistTrack, ...],
    queue: MarkerQueueName,
    playlist: str,
) -> dict[str, ArtistMarkers]:
    """Group each primary artist's unique markers in first encountered order.

    Args:
        tracks: Original complete ordered playlist facts.
        queue: Original source or auxiliary label.
        playlist: Original configured playlist identity.

    Returns:
        Original grouped unique URIs without filtering primary identities.
    """
    uris: dict[str, list[str]] = defaultdict(list)
    for track in tracks:
        if track.uri not in uris[track.primary_artist_id]:
            uris[track.primary_artist_id].append(track.uri)
    groups = {}
    for identity, markers in uris.items():
        groups[identity] = ArtistMarkers(queue, playlist, tuple(markers))
    return groups


def queue_artists(
    tracks: tuple[PlaylistTrack, ...], queue: QueueName
) -> tuple[QueueArtist, ...]:
    """Retain first artist display spelling and first encounter candidate order.

    Args:
        tracks: Original complete ordered playlist facts.
        queue: Original candidate source.

    Returns:
        Original complete unique primary-artist candidates.
    """
    artists: dict[str, QueueArtist] = {}
    for track in tracks:
        if track.primary_artist_id not in artists:
            artists[track.primary_artist_id] = QueueArtist(
                track.primary_artist_id,
                track.primary_artist_name,
                queue,
            )
    return tuple(artists.values())
