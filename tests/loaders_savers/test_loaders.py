"""Tests for JSON-backed library loaders and savers."""

import json
from pathlib import Path

from spotify_manager import loaders_savers
from spotify_manager.models.albums import SimplifiedAlbum
from spotify_manager.models.artists import SimplifiedArtist
from spotify_manager.models.file_items import ControlFileItem
from spotify_manager.models.stats import AlbumsStats
from spotify_manager.models.stats import ArtistsStats
from spotify_manager.models.stats import StatsFileItem
from spotify_manager.models.stats import StatsReport
from spotify_manager.models.stats import TracksStats
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


def simplified_album() -> SimplifiedAlbum:
    """Build one legacy total-albums entry."""
    return SimplifiedAlbum(
        spotify_id="album",
        name="Album",
        artist=SimplifiedArtist(spotify_id="artist", name="Artist"),
        ordering_string="ALBUM",
    )


def library_album() -> YourLibraryAlbum:
    """Build one saved-album mirror entry."""
    return YourLibraryAlbum(
        artist="Artist",
        album="Album",
        uri="spotify:album:album",
    )


def library_artist() -> YourLibraryArtist:
    """Build one followed-artist mirror entry."""
    return YourLibraryArtist(name="Artist", uri="spotify:artist:artist")


def library_track() -> YourLibraryTrack:
    """Build one liked-track mirror entry."""
    return YourLibraryTrack(
        artist="Artist",
        album="Album",
        track="Track",
        uri="spotify:track:track",
    )


def stats_report() -> StatsReport:
    """Build one complete stats-history record."""
    return StatsReport(
        albums_stats=AlbumsStats(
            total_saved_albums=1,
            removed_albums=0,
            added_albums=1,
            growth=1.0,
        ),
        artists_stats=ArtistsStats(
            total_followed_artists=1,
            removed_artists=0,
            added_artists=1,
            growth=1.0,
        ),
        tracks_stats=TracksStats(
            total_liked_tracks=1,
            removed_tracks=0,
            added_tracks=1,
            growth=1.0,
        ),
        avg_albums_per_artists=1,
        avg_liked_tracks_per_artists=1,
    )


def redirect_json_paths(monkeypatch, tmp_path: Path) -> dict[str, Path]:
    """Point every mutable JSON path at one temporary directory."""
    names = {
        "CONTROL_FILE_PATH": "control.json",
        "TOTAL_ALBUMS_PATH": "albums.json",
        "TOTAL_ALBUMS_NEW_PATH": "albums-new.json",
        "YOUR_LIBRARY_PATH": "library.json",
        "COMPARISON_PATH": "comparison.json",
        "TOTAL_ARTISTS_PATH": "artists.json",
        "STATS_HISTORY_PATH": "history.json",
        "STATS_FILE_PATH": "stats.json",
    }
    paths = {name: tmp_path / filename for name, filename in names.items()}
    for name, path in paths.items():
        monkeypatch.setattr(loaders_savers, name, path)
    return paths


def test_album_track_cache_handles_missing_invalid_and_valid_json(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "nested" / "cache.json"
    monkeypatch.setattr(loaders_savers, "ALBUM_TRACKS_CACHE_PATH", cache_path)

    assert loaders_savers.load_album_tracks_cache() == {}
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("not json")
    assert loaders_savers.load_album_tracks_cache() == {}

    loaders_savers.save_album_tracks_cache({"album": [{"id": "track"}]})

    assert loaders_savers.load_album_tracks_cache() == {"album": [{"id": "track"}]}


def test_all_library_json_loaders(monkeypatch, tmp_path: Path) -> None:
    paths = redirect_json_paths(monkeypatch, tmp_path)
    album = simplified_album()
    saved_album = library_album()
    artist = library_artist()
    track = library_track()
    report = stats_report()
    payloads = {
        "CONTROL_FILE_PATH": [ControlFileItem(album=album, result="keep").model_dump()],
        "TOTAL_ALBUMS_PATH": [album.model_dump()],
        "TOTAL_ALBUMS_NEW_PATH": [saved_album.model_dump()],
        "YOUR_LIBRARY_PATH": YourLibraryFile(
            tracks=[track], albums=[saved_album], artists=[artist]
        ).model_dump(),
        "COMPARISON_PATH": {"add": [], "remove": []},
        "TOTAL_ARTISTS_PATH": [artist.model_dump()],
        "STATS_HISTORY_PATH": {"2026.08.11": report.model_dump()},
    }
    for name, payload in payloads.items():
        paths[name].write_text(json.dumps(payload))

    assert loaders_savers.load_control_file()[0].album == album
    assert loaders_savers.load_total_albums_file() == [album]
    assert loaders_savers.load_total_albums_new_file() == [saved_album]
    assert loaders_savers.load_your_library_file().tracks == [track]
    assert loaders_savers.load_comparison_file() == {"add": [], "remove": []}
    assert loaders_savers.load_total_artists_file() == [artist]
    assert loaders_savers.load_stats_history_file() == {"2026.08.11": report}


def test_all_library_json_savers(monkeypatch, tmp_path: Path) -> None:
    paths = redirect_json_paths(monkeypatch, tmp_path)
    album = simplified_album()
    saved_album = library_album()
    artist = library_artist()
    control = ControlFileItem(album=album, result="keep")
    stats = StatsFileItem(
        total_saved_albums=1,
        total_listened_albums=1,
        pct_listened_albums=1.0,
        total_removed_albums=0,
        pct_removed_albums=0.0,
        total_kept_albums=1,
        pct_kept_albums=1.0,
        last_listened_to_index=0,
    )
    report = stats_report()

    loaders_savers.save_total_albums_file([album])
    loaders_savers.save_total_albums_new_file([saved_album])
    loaders_savers.save_total_artists_file([artist])
    loaders_savers.save_control_file([control])
    loaders_savers.save_stats_file(stats)
    loaders_savers.save_stats_history({"2026.08.11": report})
    loaders_savers.save_comparison_file({"add": ["album"], "remove": []})

    assert json.loads(paths["TOTAL_ALBUMS_PATH"].read_text()) == [album.model_dump()]
    assert json.loads(paths["TOTAL_ALBUMS_NEW_PATH"].read_text()) == [
        saved_album.model_dump()
    ]
    assert json.loads(paths["TOTAL_ARTISTS_PATH"].read_text()) == [artist.model_dump()]
    assert json.loads(paths["CONTROL_FILE_PATH"].read_text()) == [control.model_dump()]
    assert json.loads(paths["STATS_FILE_PATH"].read_text()) == stats.model_dump()
    assert json.loads(paths["STATS_HISTORY_PATH"].read_text()) == {
        "2026.08.11": report.model_dump()
    }
    assert json.loads(paths["COMPARISON_PATH"].read_text()) == {
        "add": ["album"],
        "remove": [],
    }
