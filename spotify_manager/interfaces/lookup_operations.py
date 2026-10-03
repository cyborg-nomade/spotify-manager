"""Run shared CLI and HTTP lookup operations and present their typed results."""

from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.album_review import review_album
from spotify_manager.application.library_lookup_run import artist_statistics
from spotify_manager.application.scrobble_lookup_run import status
from spotify_manager.bootstrap import library_lookups
from spotify_manager.bootstrap import scrobble_lookups
from spotify_manager.bootstrap.listening import album_review_ports
from spotify_manager.interfaces.presenters.albums import album_evaluation
from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.models.lookups import TrackScrobbleStatus


def evaluate_live_album(
    client: Spotify,
    *,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
    threshold: float = 0.5,
) -> AlbumEvaluation:
    """Run the typed application use case and present its existing wire result.

    Args:
        client: Existing synchronous client, owned by its caller.
        name: Exact display name when no identifier is supplied.
        album_id: Direct identifier, taking precedence over name.
        artist: Optional primary-artist disambiguation.
        threshold: Original retention threshold.

    Returns:
        The unchanged live-album response for CLI and HTTP consumers.

    Raises:
        LookupError: The album cannot be resolved uniquely.
        ValueError: Input or numeric threshold is invalid.
        RuntimeError: A Spotify response fails existing validation.
    """
    catalog, membership = album_review_ports(client)
    review = review_album(
        catalog,
        membership,
        name=name,
        album_id=album_id,
        artist=artist,
        threshold=threshold,
    )
    return album_evaluation(review)


def get_live_artist_library_stats(
    sp: Spotify,
    *,
    name: str | None = None,
    artist_id: str | None = None,
) -> ArtistLibraryStats:
    """Read one artist's saved-release and liked-track counts in the original order.

    Args:
        sp: Caller-owned synchronous Spotify client.
        name: Exact artist name when no ID is supplied.
        artist_id: Direct identity, taking precedence over the name.

    Returns:
        The unchanged artist-statistics wire result.

    Raises:
        LookupError: No unique artist can be resolved.
        ValueError: No reference is supplied.
        RuntimeError: A catalog or membership response is invalid.
    """
    return artist_statistics(library_lookups.artist_statistics(sp, name, artist_id))


def get_track_scrobble_status(
    sp: Spotify,
    *,
    name: str | None = None,
    track_id: str | None = None,
    path: Path = scrobble_lookups.DEFAULT_SCROBBLES_PATH,
    now: datetime | None = None,
) -> TrackScrobbleStatus:
    """Resolve live track identity before reading its latest play and local season.

    Args:
        sp: Caller-owned synchronous Spotify client.
        name: Exact title when no ID is supplied.
        track_id: Direct identity, taking precedence over the title.
        path: Original history export location.
        now: Optional effective observation time.

    Returns:
        The unchanged track-history wire result.

    Raises:
        LookupError: No unique track can be resolved.
        ValueError: No reference is supplied.
        RuntimeError: Spotify or history observations are invalid.
    """
    return status(scrobble_lookups.resources(sp, name, track_id, path, now))
