"""Coverage for still-registered legacy library commands."""

from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from spotify_manager.routines import convert_library_file
from spotify_manager.routines import count_items
from spotify_manager.routines import monthly_routine
from spotify_manager.utils import comparison


def album(spotify_id: str, name: str) -> SimplifiedAlbum:
    """Build one legacy total-albums entry."""
    return SimplifiedAlbum(
        spotify_id=spotify_id,
        name=name,
        artist=SimplifiedArtist(spotify_id="artist", name="Artist"),
        ordering_string=name.upper(),
    )


def exported_library() -> YourLibraryFile:
    """Build a minimal Spotify export."""
    return YourLibraryFile(
        albums=[
            YourLibraryAlbum(
                artist="Artist",
                album="Exported",
                uri="spotify:album:exported",
            )
        ],
        artists=[
            YourLibraryArtist(name="Missing", uri="spotify:artist:missing"),
            YourLibraryArtist(name="Present", uri="spotify:artist:present"),
        ],
        tracks=[
            YourLibraryTrack(
                artist="Artist",
                album="Album",
                track="Missing",
                uri="spotify:track:missing",
            ),
            YourLibraryTrack(
                artist="Artist",
                album="Album",
                track="Present",
                uri="spotify:track:present",
            ),
        ],
    )


def test_comparison_helpers_identify_and_enrich_differences(monkeypatch) -> None:
    library = exported_library()
    total = [album("stored", "Stored")]
    spotify = type(
        "Spotify",
        (),
        {
            "album": lambda _self, album_id: {
                "id": album_id,
                "name": f"Album {album_id}",
                "artists": [{"name": "Artist"}],
            }
        },
    )()
    monkeypatch.setattr(comparison, "get_spotipy_client", lambda: spotify)

    assert comparison.get_album_id_list_from_your_library_file(library) == ["exported"]
    assert comparison.get_album_id_list_from_total_albums_file(total) == ["stored"]
    assert comparison.enrich_id_to_album_dict("exported") == {
        "name": "Album exported",
        "artist": "Artist",
        "id": "exported",
    }
    assert comparison.compare_and_get_dict(
        ["shared", "exported"],
        ["shared", "stored"],
    ) == {
        "add": [{"name": "Album exported", "artist": "Artist", "id": "exported"}],
        "remove": [{"name": "Album stored", "artist": "Artist", "id": "stored"}],
    }


def test_compare_library_workflow_persists_generated_diff(monkeypatch) -> None:
    library = exported_library()
    total = [album("stored", "Stored")]
    saved: list[dict] = []
    monkeypatch.setattr(convert_library_file, "load_your_library_file", lambda: library)
    monkeypatch.setattr(convert_library_file, "load_total_albums_file", lambda: total)
    monkeypatch.setattr(
        convert_library_file,
        "compare_and_get_dict",
        lambda exported, stored: {"add": exported, "remove": stored},
    )
    monkeypatch.setattr(
        convert_library_file,
        "save_comparison_file",
        lambda value: saved.append(value),
    )

    convert_library_file.compare_your_library_and_all_albums()

    assert saved == [{"add": ["exported"], "remove": ["stored"]}]


def test_analyse_comparison_checks_both_live_statuses(monkeypatch, mocker) -> None:
    spotify = mocker.Mock()
    spotify.current_user_saved_albums_contains.side_effect = [
        [True],
        [False],
        [False],
        [True],
    ]
    monkeypatch.setattr(
        convert_library_file,
        "load_comparison_file",
        lambda: {
            "remove": [{"id": "saved"}, {"id": "removed"}],
            "add": [{"id": "missing"}, {"id": "added"}],
        },
    )

    convert_library_file.analyse_comparison(spotify)

    assert spotify.current_user_saved_albums_contains.call_count == 4


def test_convert_library_applies_confirmed_additions_and_removals(
    monkeypatch,
    mocker,
) -> None:
    spotify = mocker.Mock()
    spotify.current_user_saved_albums_contains.side_effect = [
        [False],
        [True],
        [True],
        [False],
    ]
    stored = [album("remove", "Zeta"), album("keep", "Beta")]
    added = album("add", "Alpha")
    saved: list[list[SimplifiedAlbum]] = []
    monkeypatch.setattr(convert_library_file, "load_total_albums_file", lambda: stored)
    monkeypatch.setattr(
        convert_library_file,
        "load_comparison_file",
        lambda: {
            "remove": [{"id": "remove"}, {"id": "keep"}],
            "add": [{"id": "add"}, {"id": "skip"}],
        },
    )
    monkeypatch.setattr(convert_library_file, "enrich_album", lambda *_args: added)
    monkeypatch.setattr(
        convert_library_file,
        "save_total_albums_file",
        lambda items: saved.append(list(items)),
    )

    convert_library_file.convert_your_library_file(spotify)

    assert [[item.spotify_id for item in items] for items in saved] == [["add", "keep"]]


def test_restore_library_only_restores_missing_artists_and_tracks(
    monkeypatch,
    mocker,
) -> None:
    library = exported_library()
    spotify = mocker.Mock()
    save_artist = mocker.Mock()
    save_track = mocker.Mock()
    artist_statuses = iter([False, True])
    track_statuses = iter([False, True])
    monkeypatch.setattr(convert_library_file, "load_your_library_file", lambda: library)
    monkeypatch.setattr(
        convert_library_file,
        "is_in_library_artist",
        lambda *_args: next(artist_statuses),
    )
    monkeypatch.setattr(
        convert_library_file,
        "is_in_library_track",
        lambda *_args: next(track_statuses),
    )
    monkeypatch.setattr(convert_library_file, "save_to_library_artist", save_artist)
    monkeypatch.setattr(convert_library_file, "save_to_library_track", save_track)

    convert_library_file.restore_your_library_from_file(spotify)

    save_artist.assert_called_once_with(spotify, library.artists[0])
    save_track.assert_called_once_with(spotify, library.tracks[0])


def test_monthly_routine_runs_each_stage_in_order(monkeypatch, mocker) -> None:
    spotify = mocker.Mock()
    control = [ControlFileItem(album=album("stored", "Stored"), result="keep")]
    total = [album("stored", "Stored")]
    calls: list[str] = []
    monkeypatch.setattr(monthly_routine, "load_control_file", lambda: control)
    monkeypatch.setattr(monthly_routine, "load_total_albums_file", lambda: total)
    monkeypatch.setattr(
        monthly_routine,
        "check_album_results",
        lambda *_args: calls.append("check"),
    )
    monkeypatch.setattr(
        monthly_routine,
        "update_stats",
        lambda *_args: calls.append("stats"),
    )
    monkeypatch.setattr(
        monthly_routine,
        "get_starting_index",
        lambda *_args: calls.append("index") or 7,
    )
    monkeypatch.setattr(
        monthly_routine,
        "add_monthly_albums",
        lambda *args: calls.append(f"add:{args[-1]}"),
    )

    monthly_routine.run_monthly_routines(spotify)

    assert calls == ["check", "stats", "index", "add:7"]


def test_count_artists_uses_current_export(monkeypatch) -> None:
    monkeypatch.setattr(
        count_items,
        "load_your_library_file",
        exported_library,
    )

    assert count_items.count_artists_in_library() == 2
