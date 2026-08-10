"""Tests for the New Kids CLI command."""

from types import SimpleNamespace

from rich.console import Console
from typer.testing import CliRunner

from spotify_manager import main


def release() -> main.new_kids.RankedRelease:
    """Build one ranked release for prompt and summary tests."""
    return main.new_kids.RankedRelease(
        spotify_id="release",
        uri="spotify:album:release",
        name="Release",
        release_type="Album",
        release_date="2020-01-01",
        total_tracks=10,
        primary_artist_id="artist",
        primary_artist_name="Artist",
        popularity=72,
        top_track_rank=2,
        tier=0,
        identity="RELEASE",
        saved=True,
        plain=True,
    )


def test_new_kids_release_prompt_returns_selected_release(monkeypatch) -> None:
    """The Rich release table should return the selected Spotify id."""
    candidate = release()
    monkeypatch.setattr(main.Prompt, "ask", lambda *_args, **_kwargs: "1")

    choice = main.ask_new_kids_release_choice(
        Console(),
        "Artist",
        (candidate,),
    )

    assert choice == "release"


def test_flush_new_kids_dry_run_uses_all_configured_playlists(monkeypatch) -> None:
    """The CLI should parse and pass all five destination/source settings."""
    received: dict[str, object] = {}

    def run(
        _spotify,
        new_playlist,
        queue_playlist,
        great_playlist,
        unlucky_playlist,
        newfoundland_playlist,
        choice_reader,
        **kwargs,
    ):
        assert callable(choice_reader)
        received.update(
            new_playlist=new_playlist,
            queue_playlist=queue_playlist,
            great_playlist=great_playlist,
            unlucky_playlist=unlucky_playlist,
            newfoundland_playlist=newfoundland_playlist,
            dry_run=kwargs["dry_run"],
        )
        return main.new_kids.FlushSummary(
            results=(
                main.new_kids.FlushResult(
                    artist="Artist",
                    source_track="Current",
                    source_release="Release",
                    current_liked=False,
                    consecutive_unliked=1,
                    action="advance",
                    target_track="Next",
                    target_release="Release",
                    dry_run=True,
                ),
            ),
            prefill=(main.new_kids.FillResult("Queue Artist", "Marker", "moved"),),
            postfill=(),
            playlist_length_before=9,
            playlist_length_after=10,
            paused=False,
            resumed=False,
            dry_run=True,
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            new_kids_on_the_block_playlist="spotify:playlist:new",
            the_queue_2_playlist="spotify:playlist:queue",
            great_discoveries_2026_playlist="spotify:playlist:great",
            unlucky_ones_playlist="spotify:playlist:unlucky",
            discography_newfoundland_playlist="spotify:playlist:newfoundland",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(main.new_kids, "flush_new_kids", run)

    result = CliRunner().invoke(main.app, ["flush-new-kids", "--dry-run"])

    assert result.exit_code == 0
    assert received == {
        "new_playlist": "new",
        "queue_playlist": "queue",
        "great_playlist": "great",
        "unlucky_playlist": "unlucky",
        "newfoundland_playlist": "newfoundland",
        "dry_run": True,
    }
    assert "Current" in result.output
    assert "Next" in result.output
    assert "Queue Artist" in result.output
    assert "Dry run: New Kids 9 -> 10" in result.output
