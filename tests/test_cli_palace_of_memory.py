"""Tests for the Palace of Memory CLI command."""

from datetime import UTC
from datetime import date
from datetime import datetime
from types import SimpleNamespace

from typer.testing import CliRunner

from spotify_manager import main


def test_fill_palace_dry_run_uses_configured_playlist(monkeypatch) -> None:
    """The CLI should expose refresh details and the ten-album preview."""
    received: dict[str, object] = {}
    album = main.palace_of_memory.SpotifyAlbum(
        spotify_id="album-id",
        uri="spotify:album:album-id",
        artist="Artist",
        album="Album",
        saved=True,
        similarity=1.0,
    )
    track = main.palace_of_memory.SpotifyFirstTrack(
        spotify_id="track-id",
        uri="spotify:track:track-id",
        name="Opening Track",
    )

    def fill(_spotify, playlist_id, **kwargs):
        received.update(
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
            alphabetical_start=kwargs["alphabetical_start"],
            retry_call=callable(kwargs["retry_call"]),
        )
        return main.palace_of_memory.PalaceOfMemorySummary(
            generated_at=datetime(2026, 8, 4, 10, 47, 52, tzinfo=UTC),
            playlist_id=playlist_id,
            dry_run=True,
            cutoff_date=date(2025, 12, 31),
            available_dates=6_000,
            alphabetical_start_index=0,
            alphabetical_next_index=5,
            alphabetical_cursor_overridden=True,
            playlist_length_before=0,
            playlist_length_after=1,
            album_refresh=main.palace_of_memory.SavedAlbumRefresh(
                checked_at=datetime(2026, 8, 4, tzinfo=UTC),
                previous=3_970,
                current=3_971,
                added=1,
                removed=0,
                skipped=0,
                persisted=True,
                backup_path="/tmp/albums-backup.json",
            ),
            results=(
                main.palace_of_memory.PalaceAlbumResult(
                    source="alphabetical",
                    artist="Artist",
                    album="Album",
                    spotify_album=album,
                    first_track=track,
                    action="added",
                ),
            ),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            palace_of_memory_playlist=("https://open.spotify.com/playlist/palace"),
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(main.palace_of_memory, "fill_palace_of_memory", fill)

    result = CliRunner().invoke(
        main.app,
        [
            "fill-palace-of-memory",
            "--dry-run",
            "--alphabetical-start",
            "Artist - Album",
        ],
    )

    assert result.exit_code == 0
    assert received == {
        "playlist_id": "palace",
        "dry_run": True,
        "alphabetical_start": "Artist - Album",
        "retry_call": True,
    }
    assert "Saved albums updated: 3970 -> 3971" in result.output
    assert "Palace of Memory" in result.output
    assert "Opening Track" in result.output
    assert "2025-12-31" in result.output
    assert "Alphabetical cursor (manual)" in result.output
    assert "preview only" in result.output


def test_fill_palace_can_only_persist_the_alphabetical_cursor(monkeypatch) -> None:
    """The cursor-only mode should not require or touch the Palace playlist."""
    received: dict[str, object] = {}

    def set_cursor(_spotify, position, **kwargs):
        received.update(
            position=position,
            retry_call=callable(kwargs["retry_call"]),
        )
        return main.palace_of_memory.AlphabeticalCursorUpdate(
            next_index=249,
            next_album=main.palace_of_memory.YourLibraryAlbum(
                artist="Cursor Artist",
                album="Cursor Album",
                uri="spotify:album:cursor-album",
            ),
            album_refresh=main.palace_of_memory.SavedAlbumRefresh(
                checked_at=datetime(2026, 8, 4, tzinfo=UTC),
                previous=3_983,
                current=3_983,
                added=0,
                removed=0,
                skipped=0,
                persisted=False,
                backup_path=None,
            ),
        )

    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(main.palace_of_memory, "set_alphabetical_cursor", set_cursor)
    monkeypatch.setattr(
        main.palace_of_memory,
        "fill_palace_of_memory",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("the playlist routine must not run")
        ),
    )
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: (_ for _ in ()).throw(
            AssertionError("playlist configuration must not be loaded")
        ),
    )

    result = CliRunner().invoke(
        main.app,
        ["fill-palace-of-memory", "--set-alphabetical-cursor", "250"],
    )

    assert result.exit_code == 0
    assert received == {"position": 250, "retry_call": True}
    assert "Saved albums already current: 3983 -> 3983" in result.output
    assert "Alphabetical cursor set to 250" in result.output
    assert "Cursor Artist - Cursor Album" in result.output
    assert "playlist was not changed" in " ".join(result.output.split())
