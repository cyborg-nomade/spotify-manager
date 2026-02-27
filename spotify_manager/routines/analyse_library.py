"""Analyse library routine."""

# UFI
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.processors.stats_processors import process_stats
from spotify_manager.processors.your_library_processors import process_albums
from spotify_manager.processors.your_library_processors import process_artists
from spotify_manager.processors.your_library_processors import process_tracks


def analyse_library_routine() -> None:
    """Analyse library and save stats."""
    print("Analysing library")
    your_library_file = load_your_library_file()
    albums_stats = process_albums(your_library_file.albums)
    artists_stats = process_artists(your_library_file.artists)
    tracks_stats = process_tracks(your_library_file.tracks)
    stats_report = process_stats(albums_stats, artists_stats, tracks_stats)
    print(stats_report)
    return
