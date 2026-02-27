"""Data processors for your library file."""

from spotipy import Spotify

# UFI
from spotify_manager.loaders_savers import (
    load_liked_tracks_file,
    load_total_albums_new_file,
    save_total_albums_new_file,
)
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.loaders_savers import load_total_artists_file
from spotify_manager.loaders_savers import save_liked_tracks_file
from spotify_manager.loaders_savers import save_total_albums_file
from spotify_manager.loaders_savers import save_total_artists_file
from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import TracksStats
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.utils.comparison import compare_albums
from spotify_manager.utils.comparison import compare_artists
from spotify_manager.utils.comparison import compare_tracks
from spotify_manager.utils.convertion import convert_albums
from spotify_manager.utils.growth import calculate_growth
from spotify_manager.utils.sorting import album_sort_key, artist_sort_key
from spotify_manager.utils.sorting import sort_key
from spotify_manager.utils.sorting import track_sort_key


def is_in_library_artist(sp: Spotify, artist: YourLibraryArtist) -> bool:
    """Check whether an artist is in library."""
    return sp.current_user_following_artists([artist.spotify_id])[0]


def is_in_library_track(sp: Spotify, track: YourLibraryTrack) -> bool:
    """Check whether a track is in library."""
    return sp.current_user_following_artists([track.spotify_id])[0]


def save_to_library_artist(sp: Spotify, artist: YourLibraryArtist) -> None:
    """Save artist to libary."""
    sp.user_follow_artists([artist.spotify_id])


def save_to_library_track(sp: Spotify, track: YourLibraryTrack) -> None:
    """Save track to libary."""
    sp.user_follow_artists([track.spotify_id])


def process_albums(your_library_albums: list[YourLibraryAlbum]) -> AlbumsStats:
    """Process albums and return stats."""
    total_albums_file = load_total_albums_new_file()

    previous_length = len(total_albums_file)
    new_length = len(your_library_albums)
    print("Calculating album growth...")
    growth = calculate_growth(new_length, previous_length)

    removed_albums, added_albums = compare_albums(
        total_albums_file, your_library_albums
    )

    sorted_albums = sorted(your_library_albums, key=album_sort_key)
    save_total_albums_new_file(sorted_albums)

    return AlbumsStats(
        total_saved_albums=new_length,
        removed_albums=removed_albums,
        added_albums=added_albums,
        growth=growth,
    )


def process_artists(your_library_artists: list[YourLibraryArtist]) -> ArtistsStats:
    """Process artists and return stats."""
    print("Processing artists...")
    total_artists_file = load_total_artists_file()

    previous_length = len(total_artists_file)
    new_length = len(your_library_artists)
    print("Calculating artist growth...")
    growth = calculate_growth(new_length, previous_length)

    removed_artists, added_artists = compare_artists(
        total_artists_file, your_library_artists
    )

    sorted_artists = sorted(your_library_artists, key=artist_sort_key)
    save_total_artists_file(sorted_artists)

    return ArtistsStats(
        total_followed_artists=new_length,
        removed_artists=removed_artists,
        added_artists=added_artists,
        growth=growth,
    )


def process_tracks(your_library_tracks: list[YourLibraryTrack]) -> TracksStats:
    """Process tracks and return stats."""
    print("Processing tracks...")
    liked_tracks_file = load_liked_tracks_file()

    previous_length = len(liked_tracks_file)
    new_length = len(your_library_tracks)
    print("Calculating track growth...")
    growth = calculate_growth(new_length, previous_length)

    removed_tracks, added_tracks = compare_tracks(
        liked_tracks_file, your_library_tracks
    )

    sorted_tracks = sorted(your_library_tracks, key=track_sort_key)
    save_liked_tracks_file(sorted_tracks)

    return TracksStats(
        total_liked_tracks=new_length,
        removed_tracks=removed_tracks,
        added_tracks=added_tracks,
        growth=growth,
    )
