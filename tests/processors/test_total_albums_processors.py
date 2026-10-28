"""Test data processors for total albums list."""

import asyncio

# Standard Library
from datetime import datetime

from pytest_mock import MockerFixture

# UFI
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.tracks import SimplifiedTrack
from spotify_manager.processors.total_albums_processor import add_monthly_albums
from spotify_manager.processors.total_albums_processor import append_to_playlist
from spotify_manager.processors.total_albums_processor import create_playlist
from spotify_manager.processors.total_albums_processor import (
    get_album_index_in_total_albums,
)
from spotify_manager.processors.total_albums_processor import get_months_items
from spotify_manager.processors.total_albums_processor import get_ordered_tracks
from spotify_manager.processors.total_albums_processor import update_total_album_list
from spotify_manager.processors.total_albums_processor import (
    updated_total_albums_with_results,
)
from spotify_manager.settings import Settings


settings = Settings()


def album(spotify_id: str, name: str) -> SimplifiedAlbum:
    """Build one compact album fixture."""
    return SimplifiedAlbum(
        spotify_id=spotify_id,
        name=name,
        artist={"spotify_id": "artist", "name": "Artist"},
        ordering_string=name.upper(),
    )


async def test_update_total_album_list(mocker) -> None:
    """Test get, update, save and return all saved albums."""
    spotify = mocker.Mock()
    spotify.current_user_saved_albums.return_value = {
        "total": 2,
        "items": [
            {
                "album": {
                    "id": "new",
                    "name": "Beta",
                    "artists": [{"id": "artist", "name": "Artist"}],
                }
            }
        ],
        "offset": 1,
        "next": None,
    }
    load_albums = mocker.patch(
        "spotify_manager.loaders_savers.load_total_albums_file",
        return_value=[album("stored", "Alpha")],
    )
    save_albums = mocker.patch("spotify_manager.loaders_savers.save_total_albums_file")

    result = await asyncio.to_thread(update_total_album_list, spotify, just_update=True)

    assert [item.spotify_id for item in result] == ["stored", "new"]
    assert all(isinstance(item, SimplifiedAlbum) for item in result)
    load_albums.assert_called_once_with()
    spotify.current_user_saved_albums.assert_called_once_with(
        limit=settings.limit,
        offset=1,
    )
    save_albums.assert_called_once_with(result)


def test_get_months_items() -> None:
    """Test get this months albums from all albums, starting from initial index."""
    all_albums = [album(str(index), f"Album {index:03}") for index in range(300)]

    result = get_months_items(all_albums, 3)

    assert len(result) == settings.albums_to_add
    assert result[0].spotify_id == "3"


async def test_create_playlist(mocker) -> None:
    """Test create a playlist and return id."""
    spotify = mocker.Mock()
    spotify.user_playlist_create.return_value = {"id": "valid_id"}

    result = await asyncio.to_thread(create_playlist, spotify)

    assert result == "valid_id"
    spotify.user_playlist_create.assert_called_once_with(
        "12161013970",
        name=datetime.now().strftime("%Y.%m"),
    )


async def test_update_total_album_list_reads_all_pages_and_ignores_empty_items(
    mocker,
) -> None:
    spotify = mocker.Mock()
    first_page = {
        "total": 3,
        "items": [
            {
                "album": {
                    "id": "beta",
                    "name": "Beta",
                    "artists": [{"id": "artist", "name": "Artist"}],
                }
            },
            {},
        ],
        "offset": 0,
        "next": "next",
    }
    second_page = {
        "total": 3,
        "items": [
            {
                "album": {
                    "id": "alpha",
                    "name": "Alpha",
                    "artists": [{"id": "artist", "name": "Artist"}],
                }
            }
        ],
        "offset": 2,
        "next": None,
    }
    spotify.current_user_saved_albums.return_value = first_page
    spotify.next.return_value = second_page
    save_albums = mocker.patch("spotify_manager.loaders_savers.save_total_albums_file")

    result = await asyncio.to_thread(
        update_total_album_list, spotify, just_update=False
    )

    assert [item.spotify_id for item in result] == ["alpha", "beta"]
    spotify.next.assert_called_once_with(first_page)
    save_albums.assert_called_once_with(result)


async def test_update_total_album_list_returns_safe_fallbacks_on_failure(
    mocker,
) -> None:
    spotify = mocker.Mock()
    spotify.current_user_saved_albums.side_effect = RuntimeError("offline")
    stored = [album("stored", "Stored")]
    mocker.patch(
        "spotify_manager.loaders_savers.load_total_albums_file",
        return_value=stored,
    )

    assert (
        await asyncio.to_thread(update_total_album_list, spotify, just_update=True)
    ) == stored
    assert (
        await asyncio.to_thread(update_total_album_list, spotify, just_update=False)
    ) == []


async def test_update_total_album_list_recovers_one_failed_next_page(mocker) -> None:
    spotify = mocker.Mock()
    first_page = {
        "total": 2,
        "items": [
            {
                "album": {
                    "id": "first",
                    "name": "First",
                    "artists": [{"id": "artist", "name": "Artist"}],
                }
            }
        ],
        "offset": 0,
        "next": "next",
    }
    recovered_page = {
        "total": 2,
        "items": [],
        "offset": 0,
        "next": None,
    }
    spotify.current_user_saved_albums.side_effect = [first_page, recovered_page]
    spotify.next.side_effect = RuntimeError("temporary")
    mocker.patch("spotify_manager.loaders_savers.save_total_albums_file")

    result = await asyncio.to_thread(
        update_total_album_list, spotify, just_update=False
    )

    assert [item.spotify_id for item in result] == ["first"]
    assert spotify.current_user_saved_albums.call_count == 2


async def test_get_ordered_tracks_collects_pages_and_sorts_disc_then_track(
    mocker,
) -> None:
    spotify = mocker.Mock()
    first_page = {
        "items": [
            {
                "disc_number": 2,
                "track_number": 1,
                "uri": "spotify:track:third",
            },
            None,
        ],
        "next": "next",
    }
    second_page = {
        "items": [
            {
                "disc_number": 1,
                "track_number": 2,
                "uri": "spotify:track:second",
            },
            {
                "disc_number": 1,
                "track_number": 1,
                "uri": "spotify:track:first",
            },
        ],
        "next": None,
    }
    spotify.album_tracks.return_value = first_page
    spotify.next.return_value = second_page

    result = await asyncio.to_thread(
        get_ordered_tracks, spotify, album("album", "Album")
    )

    assert [track.uri for track in result] == [
        "spotify:track:first",
        "spotify:track:second",
        "spotify:track:third",
    ]


async def test_append_to_playlist_uses_one_or_several_batches(mocker) -> None:
    spotify = mocker.Mock()
    short = [SimplifiedTrack(disc_number=1, track_number=1, uri="short")]
    long = [
        SimplifiedTrack(disc_number=1, track_number=index, uri=f"track-{index}")
        for index in range(205)
    ]

    (await asyncio.to_thread(append_to_playlist, spotify, short, "playlist"))
    (await asyncio.to_thread(append_to_playlist, spotify, long, "playlist"))

    assert [
        len(call.args[1]) for call in spotify.playlist_add_items.call_args_list
    ] == [
        1,
        100,
        100,
        5,
    ]


async def test_add_monthly_albums_updates_playlist_and_control_file(
    mocker: MockerFixture,
) -> None:
    """Verify add monthly albums updates playlist and control file.

    Args:
        mocker: Isolated mocks for the original I/O and application boundaries.
    """
    spotify = mocker.Mock()
    control: list[ControlFileItem] = []
    selected = [album("one", "One"), album("two", "Two")]
    tracks = [SimplifiedTrack(disc_number=1, track_number=1, uri="track")]
    mocker.patch(
        "spotify_manager.application.legacy_library_refresh.playlist",
        return_value="playlist",
    )
    get_tracks = mocker.patch(
        "spotify_manager.application.legacy_library_refresh.tracks",
        return_value=tracks,
    )
    append = mocker.patch(
        "spotify_manager.application.legacy_library_refresh.append_tracks"
    )
    save = mocker.patch("spotify_manager.loaders_savers.save_control_file")

    result = await asyncio.to_thread(add_monthly_albums, spotify, control, selected, 0)

    assert result is True
    assert [item.album.spotify_id for item in control] == ["one", "two"]
    assert get_tracks.call_count == 2
    assert append.call_count == 2
    save.assert_called_once_with(control)


async def test_add_monthly_albums_returns_false_when_a_stage_fails(
    mocker: MockerFixture,
) -> None:
    """Verify add monthly albums returns false when a stage fails.

    Args:
        mocker: Isolated mocks for the original I/O and application boundaries.
    """
    mocker.patch(
        "spotify_manager.infrastructure.legacy_library_resources.LegacyMonthlyLimits.count",
        side_effect=RuntimeError("failed"),
    )

    assert (
        await asyncio.to_thread(add_monthly_albums, mocker.Mock(), [], [], 0)
    ) is False


async def test_album_index_and_result_reconciliation(mocker) -> None:
    albums = [album("zeta", "Zeta"), album("alpha", "Alpha")]
    decisions = [
        ControlFileItem(album=albums[0], result="remove"),
        ControlFileItem(album=albums[1], result="keep"),
    ]
    save = mocker.patch(
        "spotify_manager.processors.total_albums_processor.save_total_albums_file"
    )

    assert get_album_index_in_total_albums("alpha", albums) == 1
    assert get_album_index_in_total_albums("missing", albums) == 0

    (await asyncio.to_thread(updated_total_albums_with_results, albums, decisions))

    assert [item.spotify_id for item in albums] == ["alpha"]
    save.assert_called_once_with(albums)
