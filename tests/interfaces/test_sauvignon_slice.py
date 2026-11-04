"""Actual Sauvignon CLI execution with isolated history, catalog and audit effects."""

import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from spotify_manager import main
from spotify_manager.bootstrap import clients
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import found_art
from spotify_manager.routines import sauvignon
from tests.interfaces.test_found_art_slice import RecommendationClock
from tests.interfaces.test_found_art_slice import _lastfm
from tests.routines.test_blast_from_past import FakeSpotify
from tests.routines.test_sauvignon import raw_spotify_track
from tests.support.runtime_resources import provided_lastfm


class AlbumSpotify(FakeSpotify):
    """Provide the original complete album search and playable first-track response."""

    async def album_tracks(
        self, album_id: str, limit: int, offset: int
    ) -> dict[str, object]:
        """Return a deterministic playable first track.

        Args:
            album_id: Original requested edition.
            limit: Original page size.
            offset: Original first page.

        Returns:
            Original shaped catalog page.
        """
        assert album_id == "album-id" and limit == 50 and offset == 0
        return {
            "items": [{"id": "first", "uri": "spotify:track:first", "name": "Opening"}]
        }


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        sauvignon_terre_neuve_playlist="blast",
        lastfm_api_key="test-key",
        lastfm_username="test-user",
    )


def _environment(monkeypatch: pytest.MonkeyPatch) -> AlbumSpotify:
    spotify = AlbumSpotify()
    query = blast.spotify_search_query(blast.Scrobble("New Song", "New", "", 0))
    spotify.search_results[query] = [raw_spotify_track(artist="New", track="New Song")]
    lastfm = _lastfm()
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "_native_review_client", AsyncMock(return_value=spotify))
    monkeypatch.setattr(clients, "LastFmClient", Mock(return_value=lastfm))
    monkeypatch.setattr(clients, "AsyncLastFmClient", provided_lastfm)
    monkeypatch.setattr(found_art, "datetime", RecommendationClock)
    monkeypatch.setattr(sauvignon, "datetime", RecommendationClock)
    return spotify


@pytest.mark.parametrize("preview", [False, True])
def test_actual_sauvignon_cli_and_restart(
    monkeypatch: pytest.MonkeyPatch, preview: bool
) -> None:
    """Run real history, cache, album selection and audit through repeated CLI calls.

    Args:
        monkeypatch: Scoped boundary substitutions.
        preview: Original preview request.
    """
    spotify = _environment(monkeypatch)
    arguments = ["fill-sauvignon-from-lastfm", "--count", "1", "--seed-count", "1"]
    if preview:
        arguments.append("--dry-run")
    first = CliRunner().invoke(main.app, arguments, input="n\nn\n")
    assert first.exit_code == 0, first.output
    assert "Opening" in first.output and "New Album" in first.output
    second = CliRunner().invoke(main.app, arguments, input="n\nn\n")
    assert second.exit_code == 0, second.output
    assert spotify.posts == (
        []
        if preview
        else [("playlists/blast/items", {"uris": ["spotify:track:first"]})]
    )
    records = sauvignon.DEFAULT_LOG_PATH.read_text().splitlines()
    assert len(records) == 2
    first_record = json.loads(records[0])
    assert first_record["dry_run"] is preview
    assert first_record["playlist_length_after"] == int(not preview)
    later = cast(list[dict[str, object]], json.loads(records[1])["results"])
    assert [row["action"] for row in later] == (["would add"] if preview else [])
    assert len(json.loads(found_art.DEFAULT_CACHE_PATH.read_text())["entries"]) == 1


@pytest.mark.parametrize("preview", [False, True])
def test_sauvignon_cli_resolves_recommended_tracks_with_album_choices(
    monkeypatch: pytest.MonkeyPatch, preview: bool
) -> None:
    """Resolve broad track results to albums through the real CLI composition.

    Args:
        monkeypatch: External client and clock substitutions.
        preview: Suppress playlist writes while retaining the selection.
    """
    spotify = _environment(monkeypatch)
    spotify.search_results.clear()
    for artist, title in (("New", "New Song"), ("Liked", "Liked Song")):
        spotify.search_results[f"{artist} {title}"] = [
            raw_spotify_track(artist="New", track="Different title")
        ]
    arguments = ["fill-sauvignon-from-lastfm", "--count", "1", "--seed-count", "1"]
    if preview:
        arguments.append("--dry-run")
    result = CliRunner().invoke(main.app, arguments, input="1\nn\n")
    assert result.exit_code == 0, result.output
    assert "Choose a Spotify album" in result.output
    assert "https://open.spotify.com/album/album-id" in result.output
    assert "Opening" in result.output
    assert bool(spotify.posts) is not preview
