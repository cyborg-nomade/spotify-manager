"""Count items in files."""

# UFI
from spotify_manager.loaders_savers import load_your_library_file


def count_artists_in_library() -> int:
    """Return the number of artists in YourLibrary file."""
    your_library_file = load_your_library_file()
    return len(your_library_file.artists)
