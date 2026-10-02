"""Original tolerant search metadata parsing before pure historical qualification."""

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.history_matching import candidate_similarity
from spotify_manager.domain.history_matching import name_similarity


def artist_names(raw: dict[str, object]) -> tuple[str, ...]:
    """Read original ordered nonempty artist names from a raw track.

    Args:
        raw: Original raw SDK track mapping.

    Returns:
        Original display names, retaining string coercion and order.
    """
    artists = raw.get("artists")
    if not isinstance(artists, list):
        return ()
    result = []
    for artist in artists:
        if isinstance(artist, dict) and artist.get("name"):
            result.append(str(artist.get("name")))
    return tuple(result)


def matching_track(
    scrobble: Scrobble,
    raw_track: object,
    search_rank: int,
    threshold: float,
) -> SpotifyTrackMatch | None:
    """Parse original metadata before applying artist and title qualification.

    Args:
        scrobble: Original export observation.
        raw_track: Original unvalidated Spotify response row.
        search_rank: Original one-based search position.
        threshold: Original title similarity floor.

    Returns:
        Complete original qualified metadata, or no matching candidate.
    """
    if not isinstance(raw_track, dict):
        return None
    spotify_id = str(raw_track.get("id") or "").strip()
    uri = str(raw_track.get("uri") or "").strip()
    track_name = str(raw_track.get("name") or "").strip()
    artists = artist_names(raw_track)
    if not spotify_id or not uri or not track_name or not artists:
        return None

    similarity = candidate_similarity(
        scrobble.artist, scrobble.track, artists, track_name, threshold
    )
    if similarity is None:
        return None

    raw_album = raw_track.get("album")
    album_name = (
        str(raw_album.get("name") or "").strip() if isinstance(raw_album, dict) else ""
    )
    album_similarity: float | None = None
    if scrobble.album:
        album_similarity = name_similarity(scrobble.album, album_name)

    popularity = raw_track.get("popularity")
    return SpotifyTrackMatch(
        spotify_id=spotify_id,
        uri=uri,
        track=track_name,
        artists=artists,
        album=album_name,
        search_rank=search_rank,
        track_similarity=similarity,
        album_similarity=album_similarity,
        popularity=popularity if isinstance(popularity, int) else None,
    )
