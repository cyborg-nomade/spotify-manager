"""Convert pure analysis counts and order original boundary models."""

from collections.abc import Sequence

from spotify_manager.domain import library_analysis as rules
from spotify_manager.domain.library_analysis import deduplicate_models
from spotify_manager.domain.library_analysis_values import ResourceCounts
from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.utils.sorting import album_sort_key
from spotify_manager.utils.sorting import artist_sort_key
from spotify_manager.utils.sorting import track_sort_key


def _album_stats(counts: ResourceCounts) -> AlbumsStats:
    return AlbumsStats(
        total_saved_albums=counts.total,
        removed_albums=counts.removed,
        added_albums=counts.added,
        growth=counts.growth,
    )


def _artist_stats(counts: ResourceCounts) -> ArtistsStats:
    return ArtistsStats(
        total_followed_artists=counts.total,
        removed_artists=counts.removed,
        added_artists=counts.added,
        growth=counts.growth,
    )


def _track_stats(counts: ResourceCounts) -> TracksStats:
    return TracksStats(
        total_liked_tracks=counts.total,
        removed_tracks=counts.removed,
        added_tracks=counts.added,
        growth=counts.growth,
    )


def stats_report_for_analysis(
    previous_albums: Sequence[YourLibraryAlbum],
    albums: Sequence[YourLibraryAlbum],
    previous_tracks: Sequence[YourLibraryTrack],
    tracks: Sequence[YourLibraryTrack],
    previous_artists: Sequence[YourLibraryArtist],
    artists: Sequence[YourLibraryArtist],
) -> StatsReport:
    """Build a stats report from exact pre/post analysis mirrors.

    Args:
        previous_albums: Original pre-analysis saved albums.
        albums: Original complete saved-album facts.
        previous_tracks: Original pre-analysis liked tracks.
        tracks: Original complete liked-track facts.
        previous_artists: Original pre-analysis followed artists.
        artists: Original complete followed-artist facts.


    Returns:
        Original size, membership-difference and growth counts.
    """
    counts = rules.stats_report_for_analysis(
        previous_albums, albums, previous_tracks, tracks, previous_artists, artists
    )
    return StatsReport(
        albums_stats=_album_stats(counts.albums),
        artists_stats=_artist_stats(counts.artists),
        tracks_stats=_track_stats(counts.tracks),
        avg_albums_per_artists=counts.avg_albums_per_artists,
        avg_liked_tracks_per_artists=counts.avg_liked_tracks_per_artists,
    )


def sort_resources(
    albums: list[YourLibraryAlbum],
    tracks: list[YourLibraryTrack],
    artists: list[YourLibraryArtist],
) -> tuple[list[YourLibraryAlbum], list[YourLibraryTrack], list[YourLibraryArtist]]:
    """Deduplicate and apply Spotify-like output ordering.

    Args:
        albums: Original complete saved-album facts.
        tracks: Original complete liked-track facts.
        artists: Original complete followed-artist facts.


    Returns:
        Original deduplicated albums, tracks and artists in output order.
    """
    return (
        sorted(deduplicate_models(albums), key=album_sort_key),
        sorted(deduplicate_models(tracks), key=track_sort_key),
        sorted(deduplicate_models(artists), key=artist_sort_key),
    )
