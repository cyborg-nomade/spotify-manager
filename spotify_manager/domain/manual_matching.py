"""Complete album observations offered for explicit catalog matching."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ManualAlbumCandidate:
    """Retain catalog metadata without automatic identity or title qualification.

    Args:
        spotify_id: Spotify album identity.
        uri: Playable album reference.
        album: Display title.
        artists: Complete ordered display credits.
        artist_ids: Ordered artist identities parallel to the display credits.
        release_type: Spotify album type before routine-specific eligibility.
        release_date: Display release date.
        total_tracks: Observed track count, or zero when unavailable.
        search_rank: Original one-based search position.
        source_track: Matched track title for track-to-album searches.
        source_track_id: Matched track identity, when applicable.
    """

    spotify_id: str
    uri: str
    album: str
    artists: tuple[str, ...]
    artist_ids: tuple[str, ...]
    release_type: str
    release_date: str
    total_tracks: int
    search_rank: int
    source_track: str = ""
    source_track_id: str = ""
