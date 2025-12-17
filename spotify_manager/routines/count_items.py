"""Count items in files."""

from spotify_manager.loaders_savers import load_your_library_file


def count_artists_in_library() -> None:
    """Return the number of artists in YourLibrary file."""
    your_library_file = load_your_library_file()
    print(len(your_library_file.artists))
