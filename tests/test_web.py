"""Tests for deployment-only web pages and Genre Reveal state."""

from collections.abc import Iterator
from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from spotipy.exceptions import SpotifyException

from spotify_manager import api
from spotify_manager import web
from spotify_manager._auth import OPEN_PATHS
from spotify_manager.routines import genre_reveal


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setattr(
        web,
        "GENRE_REVEAL_STATE_PATH",
        tmp_path / "genre_reveal_state.json",
    )
    monkeypatch.setattr(
        web,
        "GENRE_REVEAL_LOG_PATH",
        tmp_path / "genre_reveal_log.jsonl",
    )
    web.app.dependency_overrides[api.get_client] = lambda: object()
    try:
        yield TestClient(web.app)
    finally:
        web.app.dependency_overrides.pop(api.get_client, None)


def test_genre_reveal_shell_is_open_but_state_api_is_protected() -> None:
    assert "/genre-reveal" in OPEN_PATHS
    assert "/genre-reveal/" in OPEN_PATHS
    assert "/genre-reveal/state" not in OPEN_PATHS


def test_new_wine_web_labels_jump_to_later_liked_track(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert 'item.advance_reason === "next_liked_track"' in response.text
    assert 'action += " · next liked"' in response.text
    assert "job.pending_choice.terminal_release" in response.text
    assert 'data-choice="finish">Finish' in response.text
    assert "item.continuation_release" in response.text
    assert "item.continuation_track" in response.text
    assert 'id="newWineNoDiscovery"' in response.text
    assert 'q.set("no_discovery", noDiscovery ? "true" : "false")' in response.text
    assert "job.new_wine_refill" in response.text
    assert 'cellar.before + " → " + cellar.after' in response.text
    assert "cellar.removed_from_cellar" in response.text
    assert "Boolean(job.no_discovery)" in response.text


def test_genre_reveal_page_preserves_route_and_server_sync(client: TestClient) -> None:
    response = client.get("/genre-reveal")

    assert response.status_code == 200
    assert "Every Noise — nearest-neighbour route" in response.text
    assert "through 6,132 genres" in response.text
    assert 'const STATE_URL = "/genre-reveal/state"' in response.text
    assert 'const RUN_URL = "/genre-reveal/run-next"' in response.text
    assert 'id="runNext"' in response.text
    assert "everynoise-nearest-neighbour-completed-v1" in response.text
    assert "everynoise-nearest-neighbour-completed-updated-v1" in response.text
    assert "everynoise-nearest-neighbour-completed-backups-v1" in response.text
    assert "cachedUpdatedAt > serverUpdatedAt" in response.text


def test_genre_reveal_state_api_round_trip(client: TestClient) -> None:
    empty = client.get("/genre-reveal/state")
    saved = client.put(
        "/genre-reveal/state",
        json={
            "completed": ["ambient", "jazz", "ambient"],
            "hide_done": True,
        },
    )
    loaded = client.get("/genre-reveal/state")

    assert empty.status_code == 200
    assert empty.json()["completed"] == []
    assert empty.json()["updated_at"] is None
    assert saved.status_code == 200
    assert saved.json()["completed"] == ["ambient", "jazz"]
    assert saved.json()["hide_done"] is True
    assert saved.json()["updated_at"] is not None
    assert loaded.json() == saved.json()


def test_genre_reveal_source_preview(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = genre_reveal.GenreRevealSourcePreview(
        slug="kerkkoor",
        name="kerkkoor",
        every_noise_url="https://everynoise.com/engenremap-kerkkoor.html",
        source_playlist_id="source",
        source_playlist_uri="spotify:playlist:source",
        source_playlist_url="https://open.spotify.com/playlist/source",
    )
    monkeypatch.setattr(
        web.genre_reveal,
        "discover_genre_source",
        lambda slug, name: preview,
    )

    response = client.get(
        "/genre-reveal/source",
        params={"slug": "kerkkoor", "name": "kerkkoor"},
    )

    assert response.status_code == 200
    assert response.json()["source_playlist_id"] == "source"


def test_genre_reveal_run_marks_state_only_after_spotify_succeeds(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="destination"),
    )
    monkeypatch.setattr(
        web.genre_reveal,
        "process_next_genre",
        lambda client, slug, name, destination_playlist_id, log_path: (
            genre_reveal.GenreRevealRunResult(
                slug=slug,
                name=name,
                every_noise_url=("https://everynoise.com/engenremap-kerkkoor.html"),
                source_playlist_id="source",
                source_playlist_uri="spotify:playlist:source",
                source_playlist_url="https://open.spotify.com/playlist/source",
                destination_playlist_id=destination_playlist_id,
                source_track_uris=["spotify:track:0000000000000000000000"],
                added_track_uris=["spotify:track:0000000000000000000000"],
                already_present_track_uris=[],
                completed_at=datetime.now(UTC),
            )
        ),
    )

    response = client.post(
        "/genre-reveal/run-next",
        json={"slug": "kerkkoor", "name": "kerkkoor"},
    )
    state = client.get("/genre-reveal/state")

    assert response.status_code == 200
    assert response.json()["added_track_uris"] == [
        "spotify:track:0000000000000000000000"
    ]
    assert state.json()["completed"] == ["kerkkoor"]


def test_genre_reveal_failure_leaves_state_incomplete(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="destination"),
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise genre_reveal.GenreRevealSourceError("Spotify embed unavailable")

    monkeypatch.setattr(web.genre_reveal, "process_next_genre", fail)

    response = client.post(
        "/genre-reveal/run-next",
        json={"slug": "kerkkoor", "name": "kerkkoor"},
    )
    state = client.get("/genre-reveal/state")

    assert response.status_code == 502
    assert state.json()["completed"] == []


def test_genre_reveal_rate_limit_returns_promptly_and_releases_lock(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        web,
        "Settings",
        lambda: SimpleNamespace(genre_reveal_playlist="destination"),
    )

    def rate_limit(*args: object, **kwargs: object) -> None:
        raise SpotifyException(
            429,
            -1,
            "rate limited",
            headers={"Retry-After": "120"},
        )

    monkeypatch.setattr(web.genre_reveal, "process_next_genre", rate_limit)

    response = client.post(
        "/genre-reveal/run-next",
        json={"slug": "kerkkoor", "name": "kerkkoor"},
    )

    assert response.status_code == 429
    assert "after trying all configured credentials" in response.json()["detail"]
    assert "in 2 minutes" in response.json()["detail"]
    assert web._genre_reveal_run_lock.locked() is False


def test_main_page_places_playlist_routines_in_expected_order(
    client: TestClient,
) -> None:
    response = client.get("/")

    server_files_position = response.text.index('id="serverFilesCard"')
    library_mirrors_position = response.text.index('id="libraryMirrorsCard"')
    blast_position = response.text.index('id="blastCard"')
    daily_position = response.text.index('id="dailyMindRadioCard"')
    found_art_position = response.text.index('id="foundArtCard"')
    release_check_position = response.text.index('id="releaseCheckCard"')
    discography_position = response.text.index('id="discographyCard"')
    new_wine_position = response.text.index('id="newWineCard"')
    slow_listening_position = response.text.index('id="slowListeningCard"')
    something_old_position = response.text.index('id="somethingOldCard"')
    requeue_position = response.text.index('id="requeueForADreamCard"')
    palace_position = response.text.index('id="palaceOfMemoryCard"')
    scrobble_history_position = response.text.index('id="scrobbleHistoryCard"')
    genre_position = response.text.index('id="genreRevealCard"')
    artist_position = response.text.index("<!-- Artist stats -->")

    assert (
        server_files_position
        < library_mirrors_position
        < scrobble_history_position
        < blast_position
        < daily_position
        < found_art_position
        < genre_position
        < new_wine_position
        < slow_listening_position
        < something_old_position
        < requeue_position
        < palace_position
        < release_check_position
        < discography_position
        < artist_position
    )
    assert "lastfmstats-man-et-arms.json" in response.text
    assert 'id="foundArtCount"' in response.text
    assert 'value="20"' in response.text
    assert 'data-action="startFoundArt"' in response.text
    assert 'basePath: "/commands/found-art"' in response.text
    assert "restoreActiveFoundArtJobs();" in response.text
    assert 'id="releaseCheckDryRun" checked' in response.text
    assert 'data-action="startReleaseCheck"' in response.text
    assert 'data-action="releaseCheckSearch"' in response.text
    assert 'data-action="releaseCheckChoice"' in response.text
    assert '"/commands/check-new-releases-jobs/"' in response.text
    assert "job.release_check_pending_choice" in response.text
    assert "restoreActiveReleaseCheckJobs();" in response.text
    assert 'id="discographyDryRun" checked' in response.text
    assert 'data-action="startDiscography"' in response.text
    assert 'data-action="submitDiscographyReleases"' in response.text
    assert 'data-action="discographyChoice"' in response.text
    assert '"/commands/plan-discographies-jobs/"' in response.text
    assert "job.discography_pending_choice" in response.text
    assert "previousReleaseIds" in response.text
    assert "previousChoiceKey === choiceKey" in response.text
    assert "restoreActiveDiscographyJobs();" in response.text
    assert 'id="newWineDryRun" checked' in response.text
    assert 'id="newWineNoDiscovery"' in response.text
    assert 'id="refreshCache"' not in response.text
    assert 'q.set("refresh_cache"' not in response.text
    assert 'data-action="startNewWine"' in response.text
    assert 'data-action="newWineChoice"' in response.text
    assert '"/commands/flush-new-wine-jobs/"' in response.text
    assert "restoreActiveNewWineJobs();" in response.text
    assert 'id="slowListeningDryRun" checked' in response.text
    assert 'data-action="startSlowListening"' in response.text
    assert 'data-action="slowListeningChoice"' in response.text
    assert '"/commands/flush-slow-listening-jobs/"' in response.text
    assert "restoreActiveSlowListeningJobs();" in response.text
    assert 'id="somethingOldDryRun" checked' in response.text
    assert 'data-action="startSomethingOld"' in response.text
    assert 'data-action="somethingOldChoice"' in response.text
    assert '"/commands/something-old-jobs/"' in response.text
    assert 'data-choice="lastfm_top_tracks"' in response.text
    assert 'data-choice="spotify_top_tracks"' in response.text
    assert "job.something_old_ranking" in response.text
    assert "job.something_old_tracks" in response.text
    assert "restoreActiveSomethingOldJobs();" in response.text
    assert 'id="requeueForADreamDryRun" checked' in response.text
    assert 'data-action="startRequeueForADream"' in response.text
    assert 'data-action="cancelRequeueForADream"' in response.text
    assert '"/commands/flush-requeue-for-a-dream-jobs/"' in response.text
    assert "job.requeue_target_release" in response.text
    assert "job.requeue_target_track" in response.text
    assert "restoreActiveRequeueForADreamJobs();" in response.text
    assert 'id="palaceOfMemoryDryRun" checked' in response.text
    assert 'id="palaceAlphabeticalStart"' in response.text
    assert 'id="palaceAlphabeticalCursor"' in response.text
    assert 'data-action="startPalaceOfMemory"' in response.text
    assert 'data-action="setPalaceOfMemoryCursor"' in response.text
    assert 'data-action="cancelPalaceOfMemory"' in response.text
    assert '"/commands/fill-palace-of-memory-jobs/"' in response.text
    assert "job.palace_results" in response.text
    assert "job.palace_album_refresh" in response.text
    assert "restoreActivePalaceOfMemoryJobs();" in response.text
    assert 'id="scrobbleHistoryDryRun" checked' in response.text
    assert 'data-action="startScrobbleHistory"' in response.text
    assert '"/commands/update-scrobble-history-jobs/"' in response.text
    assert "job.history_export_scrobbles" in response.text
    assert "job.history_legacy_scrobbles_added" in response.text
    assert "job.history_backup_path" in response.text
    assert "restoreActiveScrobbleHistoryJobs();" in response.text
    assert 'data-action="openGenreReveal"' in response.text
    assert 'data-mode="mirror-albums"' in response.text
    assert 'data-mode="mirror-tracks"' in response.text
    assert 'data-mode="mirror-artists"' in response.text
    assert 'data-resource="artists" data-mirror-mode="incremental"' in response.text
    assert 'data-resource="artists" data-mirror-mode="full"' in response.text
    assert 'data-mirror-mode="incremental"' in response.text
    assert 'data-mirror-mode="full"' in response.text
    assert "setMirrorMode(mirrorResource, job.full_rebuild" in response.text
    assert 'endpoint += "?full_rebuild=true"' in response.text
    assert '"/commands/refresh-library-mirrors/" + resource' in response.text
    assert 'api("/library-mirrors/status")' in response.text
    assert "loadServerFilesStatus();" in response.text


def test_main_page_hides_legacy_library_and_command_cards(
    client: TestClient,
) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "<h2>Library</h2>" not in response.text
    assert "<h2>Library analyses</h2>" not in response.text
    assert "<summary>Commands</summary>" not in response.text
    assert 'data-action="countArtists"' not in response.text
    assert 'data-action="refreshLibrary"' not in response.text
    assert 'data-action="analysis" data-mode="async"' not in response.text
    assert 'data-action="analysis" data-mode="sync"' not in response.text
    assert 'data-action="analysis" data-mode="mirror-albums"' in response.text
    assert 'data-action="analysis" data-mode="mirror-tracks"' in response.text
    assert 'data-action="analysis" data-mode="mirror-artists"' in response.text
    assert '<button class="ghost" data-action="cmd"' not in response.text
    assert "restoreActiveAnalysisJobs();" in response.text


def test_main_page_uses_grouped_signal_rack_layout(
    client: TestClient,
) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert '<main class="cockpit-grid">' in response.text
    assert 'class="card system-card" id="serverFilesCard"' in response.text
    assert 'id="libraryMirrorsCard" aria-label="Live library mirrors"' in (
        response.text
    )
    assert 'id="scrobbleHistoryCard" aria-label="Last.fm scrobble history"' in (
        response.text
    )
    assert 'id="libraryMirrorFilesStatus"' in response.text
    assert 'id="scrobbleHistoryFileStatus"' in response.text
    assert 'id="serverFilesSummary"' in response.text
    assert '<span class="deck-label">Signal rack</span>' in response.text
    assert "<h2>Data signal board</h2>" in response.text
    assert 'data-server-file-date="albums_total_new.json"' in response.text
    assert 'data-server-file-date="liked_tracks_total.json"' in response.text
    assert 'data-server-file-date="artists_total.json"' in response.text
    assert 'data-server-file-date="lastfmstats-man-et-arms.json"' in response.text
    assert 'class="macro-module recovery-module"' in response.text
    assert 'class="macro-module discovery-module"' in response.text
    assert 'class="macro-module listening-module"' in response.text
    assert 'class="macro-module albums-module"' in response.text
    assert 'class="macro-module lookup-module"' in response.text
    assert 'class="card independent-module" id="releaseCheckCard"' in response.text
    assert 'class="card independent-module" id="discographyCard"' in response.text
    assert "@media (min-width: 1120px)" in response.text
    assert "@media (min-width: 760px) and (max-width: 1119px)" in response.text
    assert "justify-content: flex-end; column-gap: 4px; row-gap: 5px" in (response.text)
    assert "#blastCard .mode-switch { width: 112px; }" in response.text
    assert ".cockpit-grid { grid-template-columns: repeat(12" in response.text
    assert "background: linear-gradient(165deg" in response.text
    assert "--control-unit: 64px" in response.text
    assert "max-width: 100%; margin-left: auto" in response.text
    assert "white-space: normal; overflow-wrap: anywhere" in response.text
    assert "display: flex; flex-wrap: wrap; justify-content: flex-end" in response.text
    assert "text-overflow: ellipsis" not in response.text
    assert "html { font-size: 20px; }" in response.text
    assert ".macro-grid { display: grid; align-content: start" in response.text
    assert "function enhanceControlPanels()" in response.text
    assert "function createTerminalTrigger(scope)" in response.text
    assert 'class="card blank-console-card" aria-hidden="true"' in response.text
    assert "strip.appendChild(terminal);\n        strip.appendChild(command);" in (
        response.text
    )
    assert (
        "command.insertBefore(\n"
        "            terminal,\n"
        '            command.querySelector(".analysis-actions")'
    ) in response.text
    assert 'settings.id = "palaceSettings"' in response.text
    assert 'settingsTrigger.className = "settings-trigger"' in response.text
    assert "#blastCard .panel-strip > h2 { flex-basis: 100%" in response.text
    assert ">Check</button>" in response.text
    assert "trigger.innerHTML = '<span aria-hidden=\"true\">&gt;_</span>';" in (
        response.text
    )
    assert ".card:has(.terminal-trigger:hover) .analysis-log" in response.text
    assert "display: none; max-height: 220px" in response.text
    assert 'id="artistStatsCard"' in response.text
    assert 'id="albumEvaluationCard"' in response.text
    assert 'id="artistReference"' in response.text
    assert 'id="albumReference"' in response.text
    assert 'id="artistName"' not in response.text
    assert 'id="artistId"' not in response.text
    assert 'id="albumName"' not in response.text
    assert 'id="albumArtist"' not in response.text
    assert 'id="albumId"' not in response.text
    assert 'q.set("reference", reference)' in response.text
    assert 'document.querySelectorAll("[data-server-file-date]")' in response.text
    assert "var starts = document.querySelectorAll" in response.text
    assert (
        'showToast("Scrobble history update finished", "ok");\n'
        "        loadServerFilesStatus();"
    ) in response.text
    assert 'data-choice="skip-artist">Skip permanently</button>' in response.text
    assert 'data-choice="pending">Keep pending</button>' in response.text
    assert "choice.unattached_single" in response.text
