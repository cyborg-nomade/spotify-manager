"""Utils for sorting lists alphabetically."""

# Standard Library
import re

from pyuca import Collator

# UFI
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


def get_ordering_string(album_name: str) -> str:
    """Return the ordering string from the album name."""
    pattern = re.compile(r"(^(the|a|an)\b)?(?!\$)\W|_", re.UNICODE | re.IGNORECASE)

    tentative_ordering_str = re.sub(pattern, "", album_name)

    if tentative_ordering_str:
        return tentative_ordering_str.upper()
    else:
        return album_name.upper()


c = Collator()


def sort_key(item: SimplifiedAlbum) -> tuple[int, ...]:
    """Sort key function."""
    return c.sort_key(str(item.ordering_string))


def album_sort_key(item: YourLibraryAlbum) -> tuple[int, ...]:
    """Sort key function."""
    return c.sort_key(get_ordering_string(item.album))


def artist_sort_key(item: YourLibraryArtist) -> tuple[int, ...]:
    """Sort key function."""
    return c.sort_key(str(item.name))


def track_sort_key(item: YourLibraryTrack) -> tuple[int, ...]:
    """Sort key function."""
    return c.sort_key(str(item.track))
