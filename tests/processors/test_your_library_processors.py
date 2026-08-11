"""Tests for processors that reconcile an exported Spotify library."""

from unittest.mock import call

from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.processors.your_library_processors import is_in_library_artist
from spotify_manager.processors.your_library_processors import is_in_library_track
from spotify_manager.processors.your_library_processors import save_to_library_artist
from spotify_manager.processors.your_library_processors import save_to_library_track


def test_is_in_library_artist(mocker) -> None:
    """Return Spotify's live followed status without making network calls."""
    spotify = mocker.Mock()
    spotify.current_user_following_artists.side_effect = [[True], [False]]
    artists = [
        YourLibraryArtist(name="Followed", uri="spotify:artist:followed"),
        YourLibraryArtist(name="Not Followed", uri="spotify:artist:not-followed"),
    ]

    results = [is_in_library_artist(spotify, artist) for artist in artists]

    assert results == [True, False]
    assert spotify.current_user_following_artists.call_args_list == [
        call(["followed"]),
        call(["not-followed"]),
    ]


def test_track_restore_uses_saved_tracks_endpoints(mocker) -> None:
    spotify = mocker.Mock()
    spotify.current_user_saved_tracks_contains.return_value = [False]
    track = YourLibraryTrack(
        artist="Artist",
        album="Album",
        track="Track",
        uri="spotify:track:track-id",
    )

    assert is_in_library_track(spotify, track) is False
    save_to_library_track(spotify, track)

    spotify.current_user_saved_tracks_contains.assert_called_once_with(["track-id"])
    spotify.current_user_saved_tracks_add.assert_called_once_with(["track-id"])
    spotify.current_user_following_artists.assert_not_called()
    spotify.user_follow_artists.assert_not_called()


def test_artist_restore_uses_following_endpoints(mocker) -> None:
    spotify = mocker.Mock()
    artist = YourLibraryArtist(name="Artist", uri="spotify:artist:artist-id")

    save_to_library_artist(spotify, artist)

    spotify.user_follow_artists.assert_called_once_with(["artist-id"])
    spotify.current_user_saved_tracks_add.assert_not_called()
