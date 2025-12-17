"""."""

# UFI
from spotify_manager.client import get_spotipy_client
from spotify_manager.loaders_savers import load_your_library_file
from spotify_manager.processors.your_library_processors import is_in_library_artist


sp = get_spotipy_client()


def test_is_in_library_artist() -> None:
    """."""
    sp = get_spotipy_client()
    your_library_file = load_your_library_file()
    for artist in your_library_file.artists:
        result = is_in_library_artist(sp, artist)
        print(artist.name)
        print(result)
        assert isinstance(result, bool)
