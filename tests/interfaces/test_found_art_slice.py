"""Actual Found Art CLI and HTTP workers executing migrated use cases and storage."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import tzinfo
from functools import partial
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from typing import Self
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from spotipy import Spotify
from typer.testing import CliRunner

from spotify_manager import api
from spotify_manager import main
from spotify_manager.client.lastfm import LastFmSimilarTrack
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import found_art
from tests.interfaces.test_discovery_slice import _wait
from tests.interfaces.test_slow_listening_slice import _stop
from tests.interfaces.test_slow_listening_slice import _thread
from tests.interfaces.test_vertical_slices import _http_client
from tests.routines.test_blast_from_past import FakeSpotify
from tests.routines.test_found_art import FakeLastFm
from tests.routines.test_found_art import spotify_track


class RecommendationClock(datetime):
    """Preserve original timestamp constructor behavior for deterministic runs."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        """Return the fixed timestamp as the same class used by ISO parsing.

        Args:
            tz: Requested timezone.

        Returns:
            Fixed effective timestamp in the requested timezone.
        """
        return cls(2026, 7, 22, 12, tzinfo=UTC).astimezone(tz)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        found_art_playlist="blast",
        lastfm_api_key="test-key",
        lastfm_username="test-user",
    )


def _lastfm() -> FakeLastFm:
    lastfm = FakeLastFm()
    history = []
    similar = (
        LastFmSimilarTrack("New", "New Song", 1),
        LastFmSimilarTrack("Liked", "Liked Song", 1),
    )
    for index in range(30):
        artist, title = f"Artist {index}", f"Seed {index}"
        history.append(
            {"artist": artist, "track": title, "album": "Album", "date": 1784635200000}
        )
        lastfm.similar[(artist, title)] = similar
    found_art.DEFAULT_SCROBBLES_PATH.write_text(
        json.dumps({"username": "test-user", "scrobbles": history})
    )
    return lastfm


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    for artist, title, identity in [
        ("New", "New Song", "new"),
        ("Liked", "Liked Song", "liked"),
    ]:
        query = blast.spotify_search_query(blast.Scrobble(title, artist, "", 0))
        spotify.search_results[query] = [spotify_track(identity, title, artist)]
    spotify.liked_ids = {"liked"}
    return spotify


@dataclass(frozen=True)
class FoundArtEnvironment:
    """Real public handlers with deterministic clock and isolated external services.

    Args:
        http: Actual HTTP routes and workers.
        spotify: Existing simulated catalog, liked status and accepted appends.
        lastfm: Existing simulated history and neighborhoods.
        cache: Isolated mutable cache path.
        audit: Isolated recommendation audit destination.
    """

    http: TestClient
    spotify: FakeSpotify
    lastfm: FakeLastFm
    cache: Path
    audit: Path


@pytest.fixture
def found_art_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[FoundArtEnvironment]:
    """Compose real handlers without replacing routine or application workflows.

    Args:
        monkeypatch: Scoped outer-dependency substitutions.

    Yields:
        Real public environment with worker cleanup.
    """
    spotify, lastfm = _spotify(), _lastfm()
    threads: list[Thread] = []
    monkeypatch.setattr(found_art, "datetime", RecommendationClock)
    monkeypatch.setattr(api, "Settings", _settings)
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "client", Mock(return_value=spotify))
    monkeypatch.setattr(api, "LastFmClient", Mock(return_value=lastfm))
    monkeypatch.setattr(main, "LastFmClient", Mock(return_value=lastfm))
    monkeypatch.setattr(api, "_blast_jobs", {})
    monkeypatch.setattr(api, "Thread", partial(_thread, threads))
    try:
        yield FoundArtEnvironment(
            _http_client(monkeypatch, cast(Spotify, spotify)),
            spotify,
            lastfm,
            found_art.DEFAULT_CACHE_PATH,
            found_art.DEFAULT_LOG_PATH,
        )
    finally:
        _stop(threads)


def _audit(environment: FoundArtEnvironment) -> dict[str, object]:
    return cast(dict[str, object], json.loads(environment.audit.read_text()))


def _accepted_count(environment: FoundArtEnvironment) -> int:
    results = cast(list[dict[str, object]], _audit(environment)["results"])
    return sum(result["action"] == "added" for result in results)


def _cached_seed_count(environment: FoundArtEnvironment) -> int:
    cache = json.loads(environment.cache.read_text())
    return len(cache["entries"])


@pytest.mark.parametrize("preview", [False, True])
def test_cli_found_art_preserves_preview_cache_audit_and_live_liked_exclusions(
    found_art_environment: FoundArtEnvironment,
    preview: bool,
) -> None:
    """Run real CLI selection and storage while preview suppresses only remote append.

    Args:
        found_art_environment: Actual CLI dependencies with isolated files and clients.
        preview: Original preview request.
    """
    environment = found_art_environment
    arguments = ["found-art", "--count", "1", "--seed-count", "1"]
    if preview:
        arguments.append("--dry-run")
    result = CliRunner().invoke(main.app, arguments)
    assert result.exit_code == 0, result.output
    assert "New Song" in result.output and "Liked Song" in result.output
    assert environment.spotify.posts == (
        [] if preview else [("playlists/blast/items", {"uris": ["spotify:track:new"]})]
    )
    assert _cached_seed_count(environment) == len(environment.lastfm.similar_calls) == 1
    assert _audit(environment)["dry_run"] is preview
    assert _accepted_count(environment) == int(not preview)
    assert (
        "Spotify was unchanged" in result.output
        if preview
        else "added 1 of 1" in result.output
    )


@pytest.mark.parametrize("empty", [False, True])
def test_http_found_art_runs_real_history_cache_resolution_append_and_audit(
    found_art_environment: FoundArtEnvironment,
    empty: bool,
) -> None:
    """Complete actual workers with live liked suppression or empty neighborhoods.

    Args:
        found_art_environment: Actual HTTP handlers with isolated external services.
        empty: Supply empty neighborhoods without suppressing their cache checkpoints.
    """
    environment = found_art_environment
    if empty:
        environment.lastfm.similar.clear()
    response = environment.http.post("/commands/found-art", params={"count": 1})
    assert response.status_code == 202, response.text
    result = _wait(
        environment.http, "found-art", str(response.json()["job_id"]), "completed"
    )
    assert result["added"] == result["playlist_length_after"] == int(not empty)
    assert result["playlist_length_before"] == 0 and result["history_tracks"] == 30
    assert result["history_scrobbles"] == 30 and result["candidate_count"] == (
        0 if empty else 2
    )
    assert environment.spotify.posts == (
        [] if empty else [("playlists/blast/items", {"uris": ["spotify:track:new"]})]
    )
    assert (
        _cached_seed_count(environment) == len(environment.lastfm.similar_calls) == 30
    )
    assert _accepted_count(environment) == int(not empty)
    assert _audit(environment)["dry_run"] is False


@pytest.mark.parametrize("preview", [False, True])
def test_repeated_cli_runs_reuse_cache_and_respect_actual_prior_additions(
    found_art_environment: FoundArtEnvironment,
    preview: bool,
) -> None:
    """Reuse current-week neighborhoods while previews remain eligible on later runs.

    Args:
        found_art_environment: Actual CLI environment with isolated files and clients.
        preview: Original presentation and remote-append mode.
    """
    environment = found_art_environment
    arguments = ["found-art", "--count", "1", "--seed-count", "1"]
    if preview:
        arguments.append("--dry-run")
    first = CliRunner().invoke(main.app, arguments)
    assert first.exit_code == 0, first.output
    second = CliRunner().invoke(main.app, arguments)
    assert second.exit_code == 0, second.output
    assert len(environment.lastfm.similar_calls) == 1
    assert len(environment.spotify.posts) == int(not preview)
    records = environment.audit.read_text().splitlines()
    assert len(records) == 2
    assert json.loads(records[0])["week_start"] == "2026-07-17"
    second_record = json.loads(records[1])
    actions = [result["action"] for result in second_record["results"]]
    assert ("would add" in actions) is preview
    assert "added" not in actions
