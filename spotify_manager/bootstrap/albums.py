"""Compose live album evaluation behind the existing public helper."""

from spotipy import Spotify

from spotify_manager.application.album_review import review_album
from spotify_manager.bootstrap.listening import album_review_ports
from spotify_manager.interfaces.presenters.albums import album_evaluation
from spotify_manager.models.lookups import AlbumEvaluation


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
