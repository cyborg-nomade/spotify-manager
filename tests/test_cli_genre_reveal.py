"""Tests for the Genre Reveal CLI command."""

from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from spotify_manager import main


def test_genre_reveal_processes_first_incomplete_genre(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.json"
    log_path = tmp_path / "log.jsonl"
    opened: list[str] = []
    seen: dict[str, object] = {}

    def process(
        spotify: object,
        slug: str,
        name: str,
        destination_playlist_id: str,
        *,
        log_path: Path,
    ) -> main.genre_reveal.GenreRevealRunResult:
        seen.update(
            {
                "spotify": spotify,
                "slug": slug,
                "name": name,
                "destination": destination_playlist_id,
                "log_path": log_path,
            }
        )
        track_uris = [f"spotify:track:{index:022d}" for index in range(10)]
        return main.genre_reveal.GenreRevealRunResult(
            slug=slug,
            name=name,
            every_noise_url=(f"https://everynoise.com/engenremap-{slug}.html"),
            source_playlist_id="source",
            source_playlist_uri="spotify:playlist:source",
            source_playlist_url="https://open.spotify.com/playlist/source",
            destination_playlist_id=destination_playlist_id,
            source_track_uris=track_uris,
            added_track_uris=track_uris[:8],
            already_present_track_uris=track_uris[8:],
            completed_at=datetime.now(UTC),
        )

    spotify = object()
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="spotify:playlist:destination"),
    )
    monkeypatch.setattr(main, "client", lambda: spotify)
    monkeypatch.setattr(main.genre_reveal, "process_next_genre", process)
    monkeypatch.setattr(main.typer, "launch", opened.append)

    result = CliRunner().invoke(
        main.app,
        [
            "genre-reveal",
            "--state-path",
            str(state_path),
            "--log-path",
            str(log_path),
        ],
    )

    assert result.exit_code == 0
    assert seen == {
        "spotify": spotify,
        "slug": "kerkkoor",
        "name": "kerkkoor",
        "destination": "destination",
        "log_path": log_path,
    }
    assert main.genre_reveal.load_genre_reveal_state(state_path).completed == [
        "kerkkoor"
    ]
    assert opened == [
        "https://everynoise.com/engenremap-kerkkoor.html",
        "https://open.spotify.com/playlist/source",
    ]
    assert "8" in result.output
    assert "2" in result.output
    assert "completed kerkkoor" in result.output


def test_genre_reveal_failure_does_not_advance_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(
        main,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="destination"),
    )
    monkeypatch.setattr(main, "client", lambda: object())

    def fail(*args: object, **kwargs: object) -> None:
        raise main.genre_reveal.GenreRevealSourceError("Source unavailable")

    monkeypatch.setattr(main.genre_reveal, "process_next_genre", fail)

    result = CliRunner().invoke(
        main.app,
        [
            "genre-reveal",
            "--state-path",
            str(state_path),
            "--no-open-pages",
        ],
    )

    assert result.exit_code == 1
    assert "Source unavailable" in result.output
    assert not state_path.exists()
