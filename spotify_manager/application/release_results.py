"""Build release decisions from observed business values."""

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import PlaylistAction
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseCheckResult
from spotify_manager.domain.release_check_values import ReleaseTrack


def release_result(
    artist: RankedArtist,
    spotify_artist: SpotifyArtistCandidate,
    release: ReleaseCandidate,
    *,
    track: ReleaseTrack | None = None,
    linked_future_release: ReleaseCandidate | None = None,
    wine_cellar_action: PlaylistAction = "not applicable",
    new_vintage_action: PlaylistAction = "not applicable",
    reason: str | None = None,
    dry_run: bool,
) -> ReleaseCheckResult:
    """Build the original review outcome without storage or client dependencies.

    Args:
        artist: Original ranked Last.fm artist.
        spotify_artist: Original resolved Spotify artist.
        release: Reviewed release.
        track: Loaded marker, when available.
        linked_future_release: Original matching announced record.
        wine_cellar_action: Wine Cellar outcome.
        new_vintage_action: New Vintage outcome.
        reason: Original skip or pending reason.
        dry_run: Original preview mode.

    Returns:
        Complete original release decision.
    """
    return ReleaseCheckResult(
        artist=artist.name,
        artist_rank=artist.rank,
        artist_scrobbles=artist.scrobbles,
        spotify_artist_id=spotify_artist.spotify_id,
        release_id=release.spotify_id,
        release=release.name,
        release_type=release.release_type,
        release_date=release.release_date,
        first_track_id=track.spotify_id if track else None,
        first_track=track.name if track else None,
        linked_future_release=(
            linked_future_release.name if linked_future_release else None
        ),
        wine_cellar_action=wine_cellar_action,
        new_vintage_action=new_vintage_action,
        reason=reason,
        dry_run=dry_run,
    )
