"""Tests for the Queue 3 CLI command."""

from types import SimpleNamespace

from rich.console import Console
from typer.testing import CliRunner

from spotify_manager import main


def release(spotify_id: str, name: str) -> main.slow_listening.DiscographyRelease:
    """Build one Queue 3 release-boundary candidate."""
    return main.slow_listening.DiscographyRelease(
        spotify_id=spotify_id,
        uri=f"spotify:album:{spotify_id}",
        name=name,
        release_type="Album",
        release_date="2020-01-01",
        chronology_date="2020-01-01",
        total_tracks=10,
        primary_artist_id="artist",
        primary_artist_name="Artist",
        identity=name.casefold(),
        saved=False,
        plain=True,
        edition_rank=0,
    )


def source_track() -> main.new_wine.PlaylistTrack:
    """Build one Queue 3 prompt source."""
    source_release = main.new_wine.ReleaseCandidate(
        spotify_id="first",
        uri="spotify:album:first",
        name="First",
        release_type="Album",
        release_date="2020-01-01",
        total_tracks=10,
        primary_artist_id="artist",
        primary_artist_name="Artist",
    )
    return main.new_wine.PlaylistTrack(
        spotify_id="track",
        uri="spotify:track:track",
        name="Current",
        primary_artist_id="artist",
        primary_artist_name="Artist",
        release=source_release,
    )


def test_release_transition_prompt_can_pause(monkeypatch) -> None:
    """Queue 3 should prompt only at an album boundary and allow a clean quit."""
    prompts: list[str] = []

    def answer(prompt: str, *_args, **_kwargs) -> str:
        prompts.append(prompt)
        return "q"

    monkeypatch.setattr(main.Prompt, "ask", answer)

    choice = main.ask_queue_3_release_transition(
        Console(),
        source_track(),
        release("first", "First"),
        release("second", "Second"),
    )

    assert choice == main.queue_3.CHOICE_QUIT
    assert prompts == ["Advance to this release?"]


def test_composer_playlist_prompt_returns_owned_selection(monkeypatch) -> None:
    """The Queue 3 CLI should show ambiguous owned playlists and return the id."""
    prompts: list[str] = []

    def answer(prompt: str, *_args, **_kwargs) -> str:
        prompts.append(prompt)
        return "2"

    monkeypatch.setattr(main.Prompt, "ask", answer)
    candidates = (
        main.queue_3.OwnedPlaylist("bach-a", "Bach selections", 120),
        main.queue_3.OwnedPlaylist("bach-b", "All of Bach", 3197),
    )

    selected = main.ask_queue_3_composer_playlist(
        Console(),
        "Johann Sebastian Bach",
        candidates,
    )

    assert selected == "bach-b"
    assert prompts == ["Use which composer playlist?"]


def test_flush_queue_3_dry_run_uses_configured_playlist(monkeypatch) -> None:
    """The CLI should pass dry-run mode and both boundary readers."""
    received: dict[str, object] = {}

    def flush(_spotify, playlist_id, **kwargs):
        received.update(
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
            transition_reader=callable(kwargs["transition_reader"]),
            composer_playlist_reader=callable(kwargs["composer_playlist_reader"]),
        )
        return main.queue_3.FlushSummary(
            run_id="run",
            total=1,
            processed=1,
            advanced=0,
            changed_releases=1,
            completed_artists=0,
            skipped=0,
            annual_import=(
                main.queue_3.AnnualImportResult(
                    artist="Imported Artist",
                    track="Marker",
                    source_year=2025,
                    action="would add",
                ),
            ),
            paused=False,
            dry_run=True,
            resumed=False,
            results=(
                main.queue_3.FlushResult(
                    artist="Artist",
                    source_track="Current",
                    source_release="First",
                    action="next release",
                    target_track="Opening",
                    target_release="Second",
                    album_decision="keep",
                    album_liked_tracks=6,
                    album_total_tracks=10,
                    dry_run=True,
                ),
            ),
        )

    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_3_playlist="https://open.spotify.com/playlist/queue3",
        ),
    )
    monkeypatch.setattr(main, "review_client", lambda: object())
    monkeypatch.setattr(main.queue_3, "flush_queue_3", flush)

    result = CliRunner().invoke(main.app, ["flush-queue-3", "--dry-run"])

    assert result.exit_code == 0
    assert received == {
        "playlist_id": "queue3",
        "dry_run": True,
        "transition_reader": True,
        "composer_playlist_reader": True,
    }
    assert "Imported Artist" in result.output
    assert "Second - Opening" in result.output
    assert "Preview only" in result.output
