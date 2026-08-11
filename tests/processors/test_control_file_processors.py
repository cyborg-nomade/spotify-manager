"""Data processors for control file items."""

# UFI
from spotify_manager.loaders_savers import load_control_file
from spotify_manager.loaders_savers import load_total_albums_file
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.processors.control_file_processors import check_album_results
from spotify_manager.processors.control_file_processors import (
    get_album_results_from_library,
)
from spotify_manager.processors.control_file_processors import (
    get_index_for_first_unevaluated_album,
)
from spotify_manager.processors.control_file_processors import get_starting_index
from spotify_manager.processors.control_file_processors import get_unevaluated_albums


def album(spotify_id: str, name: str) -> SimplifiedAlbum:
    """Build one compact album fixture."""
    return SimplifiedAlbum(
        spotify_id=spotify_id,
        name=name,
        artist=SimplifiedArtist(spotify_id="artist", name="Artist"),
        ordering_string=name.upper(),
    )


def test_get_index_for_first_unevaluated_album() -> None:
    """Test get index for first unevaluated album in control file."""
    control_file = load_control_file()
    result = get_index_for_first_unevaluated_album(control_file)
    print(result)
    print(control_file[result])
    assert isinstance(result, int)
    assert result >= 0


def test_get_unevaluated_albums() -> None:
    """Test get list of unevaluated albums from control file."""
    control_file = load_control_file()
    result = get_unevaluated_albums(control_file)
    print(len(result))
    print(result[0].result)
    assert len(result) >= 200
    assert all(item.result == "" for item in result)


def test_get_album_results_from_library(mocker) -> None:
    """Test check against spotify library if albums have been removed or kept."""
    spotify = mocker.Mock()
    spotify.current_user_saved_albums_contains.side_effect = [[True], [False]]
    unevaluated_albums = [
        ControlFileItem(album=album("kept", "Kept"), result=""),
        ControlFileItem(album=album("removed", "Removed"), result=""),
    ]

    result = get_album_results_from_library(spotify, unevaluated_albums)

    assert [item.result for item in result] == ["keep", "remove"]
    assert spotify.current_user_saved_albums_contains.call_args_list == [
        mocker.call(["kept"]),
        mocker.call(["removed"]),
    ]


def test_check_album_results(mocker) -> None:
    """Test check if non evaluated albums in control file are saved in library."""
    spotify = mocker.Mock()
    control_file = [ControlFileItem(album=album("album", "Album"), result="")]
    total_albums = [control_file[0].album]
    get_results = mocker.patch(
        "spotify_manager.processors.control_file_processors."
        "get_album_results_from_library"
    )
    update_total = mocker.patch(
        "spotify_manager.processors.control_file_processors."
        "updated_total_albums_with_results"
    )
    save_control = mocker.patch(
        "spotify_manager.processors.control_file_processors.save_control_file"
    )

    result = check_album_results(spotify, control_file, total_albums)

    assert result is True
    get_results.assert_called_once_with(spotify, control_file)
    update_total.assert_called_once_with(total_albums, control_file)
    save_control.assert_called_once_with(control_file)


def test_get_starting_index() -> None:
    """Test get starting index in total album list from last listened in control."""
    control_file = load_control_file()
    total_albums_file = load_total_albums_file()
    result = get_starting_index(control_file, total_albums_file)
    print(result)
