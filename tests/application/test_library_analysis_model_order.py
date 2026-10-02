"""Verify original boundary model ordering after pure identity decisions."""

from spotify_manager.application import library_analysis_records as rules
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack


def _artist(identity: str, name: str = "Name") -> YourLibraryArtist:
    return YourLibraryArtist(name=name, uri=f"spotify:artist:{identity}")


def _album(identity: str, name: str = "Name") -> YourLibraryAlbum:
    return YourLibraryAlbum(
        artist="Credit", album=name, uri=f"spotify:album:{identity}"
    )


def _track(identity: str, name: str = "Name") -> YourLibraryTrack:
    return YourLibraryTrack(
        artist="Credit", album="Release", track=name, uri=f"spotify:track:{identity}"
    )


def test_resource_sorting_uses_original_resource_specific_order_and_latest_values() -> (
    None
):
    """Preserve original album article ordering and track/artist lexical rules."""
    albums, tracks, artists = rules.sort_resources(
        [_album("z", "Zulu"), _album("a", "The Alpha"), _album("z", "Beta")],
        [_track("z", "Zulu"), _track("a", "Alpha")],
        [_artist("z", "Zulu"), _artist("a", "Alpha")],
    )
    assert albums == [_album("a", "The Alpha"), _album("z", "Beta")]
    assert tracks == [_track("a", "Alpha"), _track("z", "Zulu")]
    assert artists == [_artist("a", "Alpha"), _artist("z", "Zulu")]
