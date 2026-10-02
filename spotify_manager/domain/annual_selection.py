"""Select original annual exact track matches, owned identities and primary markers."""

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.history_matching import SpotifyTrackMatch


def matching_playlist_ids(playlists: tuple[OwnedPlaylist, ...], name: str) -> set[str]:
    """Find distinct owned identities with the original casefold-only title match.

    Args:
        playlists: Original current complete owned facts.
        name: Original requested display title.

    Returns:
        Original distinct matching identities, including duplicate-row collapse.
    """
    matches = set()
    for playlist in playlists:
        if playlist.name.casefold() == name.casefold():
            matches.add(playlist.spotify_id)
    return matches


def selected_track(matches: tuple[SpotifyTrackMatch, ...]) -> SpotifyTrackMatch | None:
    """Prefer the first exact title match, otherwise the first original qualified match.

    Args:
        matches: Original complete ordered search qualification results.

    Returns:
        Original preferred marker or none for an empty result.
    """
    for match in matches:
        if match.track_similarity == 1.0:
            return match
    return matches[0] if matches else None


def existing_primary_marker(
    tracks: tuple[PlaylistTrack, ...], artist: str
) -> str | None:
    """Reuse the first original marker whose primary credit is the selected artist.

    Args:
        tracks: Original complete ordered Memory Lane facts.
        artist: Original exact mapped primary identity.

    Returns:
        Original first current marker or none.
    """
    for track in tracks:
        if track.primary_artist_id == artist:
            return track.uri
    return None


def pending_uris(
    requested: list[str], existing: tuple[PlaylistTrack, ...]
) -> list[str]:
    """Keep original requested order while excluding current exact URI membership.

    Args:
        requested: Original distinct batch request.
        existing: Original complete fresh playlist facts.

    Returns:
        Original absent URI subsequence.
    """
    present = {track.uri for track in existing}
    return [uri for uri in requested if uri not in present]


def marker_position(tracks: tuple[PlaylistTrack, ...], uri: str) -> int:
    """Locate the original first marker occurrence before a top-placement retry.

    Args:
        tracks: Original complete fresh playlist facts.
        uri: Original exact marker URI.

    Returns:
        Original zero-based first position.

    Raises:
        StopIteration: The original requested marker is absent.
    """
    return next(index for index, track in enumerate(tracks) if track.uri == uri)
