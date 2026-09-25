"""Read-only album assessment with explicitly supplied integration ports."""

from dataclasses import dataclass

from spotify_manager.application.music import Album
from spotify_manager.application.music import Track
from spotify_manager.application.ports.music import AlbumCatalog
from spotify_manager.application.ports.music import TrackMembership
from spotify_manager.domain.albums import AlbumAssessment
from spotify_manager.domain.albums import assess_album


@dataclass(frozen=True)
class AlbumReview:
    """Observed album facts and the corresponding retention decision.

    Args:
        album: Resolved display identity.
        tracks: Ordered catalog tracks.
        liked: Corresponding liked flags, including false for missing identifiers.
        assessment: The pure retention policy outcome.
        threshold: The caller's original threshold.
    """

    album: Album
    tracks: tuple[Track, ...]
    liked: tuple[bool, ...]
    assessment: AlbumAssessment
    threshold: float


def _track_ids(tracks: tuple[Track, ...]) -> tuple[str, ...]:
    identifiers = []
    for track in tracks:
        if track.spotify_id:
            identifiers.append(track.spotify_id)
    return tuple(identifiers)


def _membership_key(track: Track) -> str:
    if track.membership_key is not None:
        return track.membership_key
    return str(track.spotify_id)


def review_album(
    catalog: AlbumCatalog,
    membership: TrackMembership,
    *,
    name: str | None = None,
    album_id: str | None = None,
    artist: str | None = None,
    threshold: float = 0.5,
) -> AlbumReview:
    """Gather fresh album observations and apply the existing keep rule.

    Args:
        catalog: Album resolution and ordered track access.
        membership: Live liked-status access with its existing batching policy.
        name: Album name when the identifier is unknown.
        album_id: Direct album identifier, taking precedence over the name.
        artist: Optional name disambiguation.
        threshold: Fraction used by the existing floor-based rule.

    Returns:
        Typed observations and a retention decision, without wire-model coupling.

    Raises:
        LookupError: The album cannot be resolved uniquely.
        ValueError: Required input or numeric threshold is invalid.
        RuntimeError: An integration rejects a response or cannot complete a read.
    """
    album = catalog.resolve_album(name=name, album_id=album_id, artist=artist)
    tracks = catalog.album_tracks(album.spotify_id)
    statuses = membership.liked_tracks(_track_ids(tracks))
    liked = tuple(statuses.get(_membership_key(track), False) for track in tracks)
    assessment = assess_album(len(tracks), sum(liked), threshold)
    return AlbumReview(album, tracks, liked, assessment, threshold)
