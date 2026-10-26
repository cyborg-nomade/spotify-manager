"""Tests for the FastAPI interface with isolated Spotify and file dependencies."""

from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from time import sleep
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy.exceptions import SpotifyException

from spotify_manager import api
from spotify_manager.api import app
from spotify_manager.api import get_analysis_client
from spotify_manager.api import get_client
from spotify_manager.api import get_interactive_client
from spotify_manager.api import get_library
from spotify_manager.core.library_data.service import ArtifactStatus
from spotify_manager.infrastructure.routine_state_codecs import ReleaseCheckStateCodec
from spotify_manager.interfaces.http import jobs as http_jobs
from spotify_manager.interfaces.http.workers.slow_listening import SlowListeningWorker
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack
from tests.support.feature_invocation import FeatureInvocation
from tests.support.runtime_resources import UnexpectedInteraction
from tests.support.wine_invocation import WineInvocation


def _library() -> YourLibraryFile:
    return YourLibraryFile(
        tracks=[
            YourLibraryTrack(
                artist="Radiohead",
                album="OK Computer",
                track="Airbag",
                uri="spotify:track:t1",
            ),
            YourLibraryTrack(
                artist="Radiohead",
                album="OK Computer",
                track="Karma Police",
                uri="spotify:track:t2",
            ),
        ],
        albums=[
            YourLibraryAlbum(
                artist="Radiohead", album="OK Computer", uri="spotify:album:alb1"
            )
        ],
        artists=[YourLibraryArtist(name="Radiohead", uri="spotify:artist:art1")],
    )


class FakeSpotify:
    """Minimal spotipy stand-in for API endpoint tests."""

    def __init__(self) -> None:
        self.event_callback = None

    def set_event_callback(self, callback):
        previous = self.event_callback
        self.event_callback = callback
        return previous

    def search(
        self,
        q,
        limit=10,
        offset=0,
        type="track",  # noqa: A002
        market=None,
    ):
        if type == "artist":
            return {"artists": {"items": [{"id": "art1", "name": "Radiohead"}]}}
        if type == "album":
            items = []
            if "Nope" not in q:
                items = [
                    {
                        "id": "alb1",
                        "name": "OK Computer",
                        "artists": [{"id": "art1", "name": "Radiohead"}],
                    }
                ]
            return {"albums": {"items": items}}
        raise AssertionError(f"unexpected search type: {type}")

    def artist(self, artist_id):
        return {"id": artist_id, "name": "Radiohead"}

    def artist_albums(
        self,
        artist_id,
        album_type=None,
        include_groups=None,
        country=None,
        limit=20,
        offset=0,
    ):
        return {
            "items": [
                {
                    "id": "alb1",
                    "name": "OK Computer",
                    "artists": [{"id": "art1", "name": "Radiohead"}],
                }
            ],
            "next": None,
        }

    def albums(self, album_ids, market=None):
        return {
            "albums": [
                {
                    "id": album_id,
                    "name": "OK Computer",
                    "artists": [{"id": "art1", "name": "Radiohead"}],
                    "tracks": self.album_tracks(album_id),
                }
                for album_id in album_ids
            ]
        }

    def album(self, album_id, market=None):
        return {
            "id": album_id,
            "name": "OK Computer",
            "artists": [{"id": "art1", "name": "Radiohead"}],
        }

    def album_tracks(self, album_id, limit=50, offset=0):
        return {
            "items": [
                {
                    "id": "t1",
                    "name": "Airbag",
                    "uri": "spotify:track:t1",
                    "artists": [{"id": "art1", "name": "Radiohead"}],
                },
                {
                    "id": "t2",
                    "name": "Karma Police",
                    "uri": "spotify:track:t2",
                    "artists": [{"id": "art1", "name": "Radiohead"}],
                },
                {
                    "id": "t3",
                    "name": "Let Down",
                    "uri": "spotify:track:t3",
                    "artists": [{"id": "art1", "name": "Radiohead"}],
                },
            ],
            "next": None,
        }

    def current_user_saved_albums_contains(self, album_ids):
        return [album_id == "alb1" for album_id in album_ids]

    def current_user_saved_tracks_contains(self, track_ids=None):
        return [track_id in {"t1", "t2"} for track_id in (track_ids or [])]


@pytest.fixture
def client() -> TestClient:
    from spotify_manager import api

    with api._analysis_jobs_lock:
        api._analysis_jobs.clear()
    with api._blast_jobs_lock:
        api._blast_jobs.clear()
    app.dependency_overrides[get_client] = lambda: FakeSpotify()
    app.dependency_overrides[get_analysis_client] = lambda: FakeSpotify()
    app.dependency_overrides[get_interactive_client] = lambda: FakeSpotify()
    app.dependency_overrides[get_library] = _library
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    with api._analysis_jobs_lock:
        api._analysis_jobs.clear()
    with api._blast_jobs_lock:
        api._blast_jobs.clear()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_release_check_state_browser_restore_uses_central_revision_history(
    client: TestClient,
) -> None:
    """Release check state browser restore uses central revision history.

    Args:
        client: Original client.
    """
    state_access = api.get_state_service().namespace(
        "release_check",
        ReleaseCheckStateCodec(),
    )
    state = api.release_check._default_state()
    state["updated_at"] = datetime.now(UTC).isoformat()
    state_access.load()
    state_access.save(state)

    first = client.get("/commands/check-new-releases-state")
    fingerprint = first.json()["fingerprint"]
    unchanged = client.get(
        "/commands/check-new-releases-state",
        params={"known_fingerprint": fingerprint},
    )
    candidate = first.json()["state"]
    current_updated_at = datetime.fromisoformat(candidate["updated_at"])
    candidate["updated_at"] = (current_updated_at + timedelta(minutes=1)).isoformat()
    candidate["artist_mappings"]["artist"] = {"spotify_id": "spotify-artist"}

    restored = client.put(
        "/commands/check-new-releases-state",
        json={
            "expected_server_fingerprint": fingerprint,
            "state": candidate,
        },
    )

    assert first.status_code == 200
    assert first.json()["state"] is not None
    assert unchanged.json()["state"] is None
    assert restored.status_code == 200
    assert restored.json()["state"]["artist_mappings"]["artist"] == {
        "spotify_id": "spotify-artist"
    }
    assert restored.json()["backup_path"] is None

    stale = client.put(
        "/commands/check-new-releases-state",
        json={
            "expected_server_fingerprint": restored.json()["fingerprint"],
            "state": first.json()["state"],
        },
    )
    assert stale.status_code == 409


def test_shared_state_can_be_viewed_edited_and_exported(client: TestClient) -> None:
    initial = client.get("/state")
    summary = client.get("/state/summary")
    payload = initial.json()
    document = payload["document"]
    timestamp = datetime.now(UTC).isoformat()
    document["namespaces"]["manual_test"] = {
        "updated_at": timestamp,
        "value": {"enabled": True},
    }
    document["updated_at"] = timestamp

    saved = client.put(
        "/state",
        json={
            "expected_revision": payload["revision"],
            "document": document,
        },
    )
    stale = client.put(
        "/state",
        json={
            "expected_revision": payload["revision"],
            "document": document,
        },
    )
    exported = client.get("/state/export")

    assert initial.status_code == 200
    assert summary.status_code == 200
    assert summary.json()["revision"] == payload["revision"]
    assert saved.status_code == 200
    assert saved.json()["document"]["namespaces"]["manual_test"]["value"] == {
        "enabled": True
    }
    assert stale.status_code == 409
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/json")
    assert "attachment; filename=" in exported.headers["content-disposition"]
    assert exported.json()["document"]["namespaces"]["manual_test"]["value"]["enabled"]


def test_shared_state_namespace_editor_is_schema_driven_and_guarded(
    client: TestClient,
) -> None:
    initial = client.get("/state").json()
    schema = client.get("/state/schema")
    saved = client.put(
        "/state/namespaces/discography",
        json={
            "expected_revision": initial["revision"],
            "value": {"version": 1, "next_queue": "memory_lane"},
        },
    )
    invalid_choice = client.put(
        "/state/namespaces/discography",
        json={
            "expected_revision": saved.json()["revision"],
            "value": {"version": 1, "next_queue": "unknown"},
        },
    )
    read_only = client.put(
        "/state/namespaces/discography",
        json={
            "expected_revision": saved.json()["revision"],
            "value": {"version": 2, "next_queue": "requeue"},
        },
    )
    stale = client.put(
        "/state/namespaces/discography",
        json={
            "expected_revision": initial["revision"],
            "value": {"version": 1, "next_queue": "requeue"},
        },
    )
    unknown = client.put(
        "/state/namespaces/missing",
        json={"expected_revision": saved.json()["revision"], "value": {}},
    )

    assert schema.status_code == 200
    assert schema.json()["namespaces"]["discography"]["rules"][1]["options"] == [
        "newfoundland",
        "requeue",
        "memory_lane",
    ]
    assert saved.status_code == 200
    assert saved.json()["document"]["namespaces"]["discography"]["value"] == {
        "version": 1,
        "next_queue": "memory_lane",
    }
    assert invalid_choice.status_code == 422
    assert read_only.status_code == 422
    assert stale.status_code == 409
    assert unknown.status_code == 404


def test_release_check_state_restore_rejects_an_active_job(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "release-check-state.json"
    monkeypatch.setattr(http_jobs, "RELEASE_CHECK_STATE_PATH", state_path)
    state = api.release_check._default_state()
    api.release_check.save_state(state, state_path)
    snapshot = client.get("/commands/check-new-releases-state").json()
    snapshot["state"]["updated_at"] = (
        datetime.now(UTC) + timedelta(minutes=1)
    ).isoformat()
    job = api._BlastJob(
        result=api.BlastJobResult(
            job_id="active-release-check",
            command="check_new_releases",
            status="running",
        )
    )
    with api._blast_jobs_lock:
        api._blast_jobs[job.result.job_id] = job

    response = client.put(
        "/commands/check-new-releases-state",
        json={
            "expected_server_fingerprint": snapshot["fingerprint"],
            "state": snapshot["state"],
        },
    )

    assert response.status_code == 409
    assert "active" in response.json()["detail"]


def test_release_state_timestamp_and_freshness_helpers() -> None:
    assert api._state_timestamp(None) is None
    assert api._state_timestamp("not-a-timestamp") is None
    assert api._state_timestamp("2026-08-17T12:00:00") == datetime(
        2026,
        8,
        17,
        12,
        tzinfo=UTC,
    )
    candidate = api.release_check._default_state()
    candidate["updated_at"] = "2026-08-17T12:00:00+00:00"
    current = api.release_check._default_state()

    assert api._release_state_is_newer(candidate, current) is True
    assert api._release_state_is_newer(current, candidate) is False


def test_auth_check(client: TestClient) -> None:
    assert client.get("/auth/check").json() == {"status": "ok"}


def test_library_mirror_status_reports_server_timestamps(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spotify_manager.interfaces.http import jobs as http_jobs

    albums = tmp_path / "albums_total_new.json"
    tracks = tmp_path / "liked_tracks_total.json"
    artists = tmp_path / "artists_total.json"
    scrobbles = tmp_path / "lastfmstats-man-et-arms.json"
    albums.write_text("[]")
    artists.write_text("[]")
    scrobbles.write_text("{}")
    monkeypatch.setattr(
        http_jobs,
        "LIBRARY_MIRROR_FILE_PATHS",
        (albums, tracks, artists, scrobbles),
    )

    response = client.get("/library-mirrors/status")

    assert response.status_code == 200
    files = response.json()["files"]
    assert files[0]["filename"] == "albums_total_new.json"
    assert files[0]["exists"] is True
    assert datetime.fromisoformat(files[0]["updated_at"]).tzinfo is not None
    assert files[1] == {
        "filename": "liked_tracks_total.json",
        "exists": False,
        "updated_at": None,
    }
    assert files[2]["filename"] == "artists_total.json"
    assert files[2]["exists"] is True
    assert datetime.fromisoformat(files[2]["updated_at"]).tzinfo is not None
    assert files[3]["filename"] == "lastfmstats-man-et-arms.json"
    assert files[3]["exists"] is True
    assert datetime.fromisoformat(files[3]["updated_at"]).tzinfo is not None


def test_library_mirror_status_prefers_durable_manifest(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DurableData:
        def statuses(self):
            return (
                ArtifactStatus(
                    name="albums",
                    filename="albums_total_new.json",
                    exists=True,
                    updated_at="2026-08-24T12:00:00+00:00",
                    size_bytes=2,
                    sha256="0" * 64,
                    source="test refresh",
                    local_current=True,
                ),
            )

    monkeypatch.setattr(http_jobs, "get_library_data_service", DurableData)

    response = client.get("/library-mirrors/status")

    assert response.status_code == 200
    assert response.json() == {
        "files": [
            {
                "filename": "albums_total_new.json",
                "exists": True,
                "updated_at": "2026-08-24T12:00:00+00:00",
            }
        ]
    }


def test_artist_stats_endpoint(client: TestClient) -> None:
    def fail_if_export_is_loaded():
        raise AssertionError("live artist stats must not load YourLibrary.json")

    app.dependency_overrides[get_library] = fail_if_export_is_loaded
    try:
        resp = client.get("/artists/stats", params={"name": "radiohead"})
    finally:
        app.dependency_overrides[get_library] = _library
    assert resp.status_code == 200
    body = resp.json()
    assert body["artist_id"] == "art1"
    assert body["liked_tracks"] == 2
    assert body["saved_releases"] == 1
    assert body["source"] == "spotify-live"


def test_artist_stats_requires_an_argument(client: TestClient) -> None:
    assert client.get("/artists/stats").status_code == 400


def test_artist_stats_accepts_spotify_share_link(client: TestClient) -> None:
    artist_id = "4Z8W4fKeB5YxbusRsdQVPb"

    resp = client.get(
        "/artists/stats",
        params={"reference": f"https://open.spotify.com/artist/{artist_id}?si=test"},
    )

    assert resp.status_code == 200
    assert resp.json()["artist_id"] == artist_id


def test_album_evaluation_endpoint(client: TestClient) -> None:
    def fail_if_export_is_loaded():
        raise AssertionError("live album evaluation must not load YourLibrary.json")

    app.dependency_overrides[get_library] = fail_if_export_is_loaded
    try:
        resp = client.get("/albums/evaluation", params={"name": "OK Computer"})
    finally:
        app.dependency_overrides[get_library] = _library
    assert resp.status_code == 200
    body = resp.json()
    assert body["album_id"] == "alb1"
    assert body["decision"] == "keep"  # 2/3 liked
    assert body["total_tracks"] == 3
    assert body["liked_tracks"] == 2
    assert body["source"] == "spotify-live"
    assert body["from_cache"] is False


def test_album_evaluation_accepts_spotify_share_link(client: TestClient) -> None:
    album_id = "6dVIqQ8qmQ5GBnJ9shOYGE"

    resp = client.get(
        "/albums/evaluation",
        params={"reference": f"https://open.spotify.com/album/{album_id}?si=test"},
    )

    assert resp.status_code == 200
    assert resp.json()["album_id"] == album_id


def test_album_evaluation_not_found(client: TestClient) -> None:
    resp = client.get("/albums/evaluation", params={"name": "Nope"})
    assert resp.status_code == 404


def test_track_scrobble_endpoint_accepts_spotify_share_link(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    captured: dict[str, object] = {}

    def lookup(_spotify, **kwargs):
        captured.update(kwargs)
        return api.TrackScrobbleStatus(
            track_name="Bohemian Rhapsody",
            track_id="4u7EnebtmKWzUH433cf5Qv",
            artist_name="Queen",
            album_name="A Night at the Opera",
            last_scrobbled_at=datetime(2026, 8, 20, 21, 15, tzinfo=UTC),
            last_scrobble_season="Summer 2026",
            current_season="Summer 2026",
            in_current_season=True,
            source="spotify-live + lastfm-history",
        )

    monkeypatch.setattr(http_jobs, "get_track_scrobble_status", lookup)

    response = client.get(
        "/tracks/scrobbles",
        params={
            "reference": (
                "https://open.spotify.com/track/4u7EnebtmKWzUH433cf5Qv?si=test"
            )
        },
    )

    assert response.status_code == 200
    assert captured["track_id"] == "4u7EnebtmKWzUH433cf5Qv"
    assert captured["name"] is None
    assert response.json()["in_current_season"] is True


def test_track_scrobble_endpoint_requires_an_argument(client: TestClient) -> None:
    response = client.get("/tracks/scrobbles")

    assert response.status_code == 400
    assert "provide a track name" in response.json()["detail"]


def test_track_scrobble_ambiguity_returns_candidates(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    def fail(*_args: object, **_kwargs: object) -> None:
        raise api.AmbiguousTrackError(
            "ambiguous",
            [{"track": "Song", "artist": "Artist", "album": "Album", "id": "id"}],
        )

    monkeypatch.setattr(http_jobs, "get_track_scrobble_status", fail)

    response = client.get("/tracks/scrobbles", params={"name": "Song"})

    assert response.status_code == 409
    assert response.json()["candidates"][0]["artist"] == "Artist"


def test_live_lookup_spotify_500_is_reported_as_bad_gateway(
    client: TestClient,
) -> None:
    class FailingSpotify:
        def search(self, **kwargs):
            raise SpotifyException(500, -1, "Spotify unavailable")

    app.dependency_overrides[get_client] = FailingSpotify

    resp = client.get("/artists/stats", params={"name": "Radiohead"})

    assert resp.status_code == 502
    assert resp.json()["detail"] == (
        "Spotify request failed (HTTP 500): Spotify unavailable"
    )


def test_live_lookup_connection_failure_is_reported_as_bad_gateway(
    client: TestClient,
) -> None:
    class FailingSpotify:
        def search(self, **kwargs):
            raise RequestsConnectionError("connection reset")

    app.dependency_overrides[get_client] = FailingSpotify

    resp = client.get("/artists/stats", params={"name": "Radiohead"})

    assert resp.status_code == 502
    assert resp.json()["detail"] == (
        "Spotify could not be reached after several attempts. Please try again shortly."
    )


def test_count_artists_endpoint(client: TestClient, monkeypatch) -> None:
    from spotify_manager.interfaces.http import jobs as http_jobs

    monkeypatch.setattr(http_jobs, "count_artists_in_library", lambda: 42)
    resp = client.get("/commands/count-artists")
    assert resp.json() == {"count": 42}


def test_refresh_library_endpoint(client: TestClient) -> None:
    response = client.post("/library/refresh")

    assert response.status_code == 200
    assert response.json() == {
        "command": "library_refresh",
        "status": "completed",
        "detail": None,
    }


def test_legacy_command_endpoints_delegate_to_workflows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spotify_manager.interfaces.http import jobs as http_jobs

    calls: list[tuple[str, object | None]] = []
    monkeypatch.setattr(
        http_jobs,
        "compare_your_library_and_all_albums",
        lambda: calls.append(("compare", None)),
    )
    monkeypatch.setattr(
        http_jobs,
        "convert_your_library_file",
        lambda spotify: calls.append(("convert", spotify)),
    )
    monkeypatch.setattr(
        http_jobs,
        "run_monthly_routines",
        lambda spotify: calls.append(("monthly", spotify)),
    )
    monkeypatch.setattr(
        http_jobs,
        "update_total_album_list",
        lambda spotify, just_update: (
            calls.append((f"update:{just_update}", spotify)) or [1, 2]
        ),
    )
    monkeypatch.setattr(
        http_jobs,
        "restore_your_library_from_file",
        lambda spotify: calls.append(("restore", spotify)),
    )
    monkeypatch.setattr(
        http_jobs,
        "analyse_comparison",
        lambda spotify: calls.append(("analyse", spotify)),
    )

    monthly = client.post("/commands/monthly-routines")
    update = client.post(
        "/commands/update-total-albums",
        params={"just_update": "true"},
    )
    restore = client.post("/commands/restore-your-library")
    compare = client.post("/commands/compare-lib-files")
    analyse = client.post("/commands/analyse-comp")
    convert = client.post("/commands/convert-lib")

    assert monthly.json()["command"] == "monthly_routines"
    assert update.json()["detail"] == "2 albums in list"
    assert restore.json()["command"] == "restore_your_library"
    assert compare.json()["command"] == "compare_lib_files"
    assert analyse.json()["command"] == "analyse_comp"
    assert convert.json()["command"] == "convert_lib"
    assert [name for name, _client in calls] == [
        "compare",
        "convert",
        "monthly",
        "update:True",
        "restore",
        "compare",
        "analyse",
        "convert",
    ]
    assert all(
        isinstance(spotify, FakeSpotify)
        for _name, spotify in calls
        if spotify is not None
    )


@pytest.mark.parametrize(
    ("error", "status_code", "candidates"),
    [
        (api.ArtistNotFoundError("missing"), 404, None),
        (
            api.AmbiguousArtistError("ambiguous", [{"id": "artist"}]),
            409,
            [{"id": "artist"}],
        ),
        (api.SpotifyLookupResponseError("malformed"), 502, None),
    ],
)
def test_artist_lookup_domain_errors_use_structured_responses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
    candidates: list[dict[str, str]] | None,
) -> None:
    from spotify_manager.interfaces.http import jobs as http_jobs

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(http_jobs, "get_live_artist_library_stats", fail)

    response = client.get("/artists/stats", params={"name": "Artist"})

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)
    if candidates is not None:
        assert response.json()["candidates"] == candidates


@pytest.mark.parametrize(
    ("error", "status_code", "candidates"),
    [
        (api.AlbumNotFoundError("missing"), 404, None),
        (
            api.AmbiguousAlbumError("ambiguous", [{"id": "album"}]),
            409,
            [{"id": "album"}],
        ),
    ],
)
def test_album_lookup_domain_errors_use_structured_responses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
    candidates: list[dict[str, str]] | None,
) -> None:
    from spotify_manager import api

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(api, "review_album", fail)

    response = client.get("/albums/evaluation", params={"name": "Album"})

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)
    if candidates is not None:
        assert response.json()["candidates"] == candidates


@pytest.mark.parametrize(
    ("status_code", "expected_status"),
    [(400, 400), (403, 403), (404, 404), (500, 502)],
)
def test_spotify_lookup_error_preserves_only_safe_client_statuses(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    expected_status: int,
) -> None:
    from spotify_manager.interfaces.http import jobs as http_jobs

    def fail(*_args: object, **_kwargs: object) -> None:
        raise SpotifyException(status_code, -1, "Spotify failed")

    monkeypatch.setattr(http_jobs, "get_live_artist_library_stats", fail)

    response = client.get("/artists/stats", params={"name": "Artist"})

    assert response.status_code == expected_status
    assert f"HTTP {status_code}" in response.json()["detail"]


def test_spotify_lookup_rate_limit_returns_retry_header(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spotify_manager.interfaces.http import jobs as http_jobs

    def fail(*_args: object, **_kwargs: object) -> None:
        raise SpotifyException(
            429,
            -1,
            "rate limited",
            headers={"Retry-After": "120"},
        )

    monkeypatch.setattr(http_jobs, "get_live_artist_library_stats", fail)

    response = client.get("/artists/stats", params={"name": "Artist"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "120"
    assert "in 2 minutes" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "reference", "message"),
    [
        ("/artists/stats", "spotify:artist:bad", "invalid Spotify artist URI"),
        ("/albums/evaluation", "spotify:album:bad", "invalid Spotify album URI"),
        ("/tracks/scrobbles", "spotify:track:bad", "invalid Spotify track URI"),
    ],
)
def test_live_lookup_rejects_invalid_references(
    client: TestClient,
    path: str,
    reference: str,
    message: str,
) -> None:
    response = client.get(path, params={"reference": reference})

    assert response.status_code == 400
    assert response.json()["detail"] == message


def test_album_evaluation_requires_an_argument(client: TestClient) -> None:
    response = client.get("/albums/evaluation")

    assert response.status_code == 400
    assert "provide an album name" in response.json()["detail"]


def test_album_evaluation_connection_failure_is_reported_as_bad_gateway(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spotify_manager import api

    def fail(*_args: object, **_kwargs: object) -> None:
        raise RequestsConnectionError("connection reset")

    monkeypatch.setattr(api, "review_album", fail)

    response = client.get("/albums/evaluation", params={"name": "Album"})

    assert response.status_code == 502
    assert "could not be reached" in response.json()["detail"]


def test_cached_dependency_factories_use_expected_client_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    clients = iter([object(), object(), object()])
    monkeypatch.setattr(
        http_jobs,
        "get_spotipy_client",
        lambda **kwargs: calls.append(kwargs) or next(clients),
    )
    monkeypatch.setattr(http_jobs, "load_your_library_file", _library)
    for dependency in (
        api.get_client,
        api.get_analysis_client,
        api.get_interactive_client,
        api.get_library,
    ):
        dependency.cache_clear()

    assert api.get_client() is api.get_client()
    assert api.get_analysis_client() is api.get_analysis_client()
    assert api.get_interactive_client() is api.get_interactive_client()
    assert api.get_library() is api.get_library()
    assert calls == [
        {"allow_interactive_auth": False},
        {
            "retries": 0,
            "status_retries": 0,
            "status_forcelist": (999,),
            "allow_interactive_auth": False,
        },
        {
            "retries": 0,
            "status_retries": 0,
            "status_forcelist": (999,),
            "allow_interactive_auth": False,
        },
    ]
    for dependency in (
        api.get_client,
        api.get_analysis_client,
        api.get_interactive_client,
        api.get_library,
    ):
        dependency.cache_clear()


def test_job_helpers_copy_bound_logs_and_reject_unknown_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = api._AnalysisJob(
        result=api.AnalysisJobResult(
            job_id="analysis",
            command="async",
            resources={},
        ),
        cancel_event=Event(),
    )
    blast = api._BlastJob(
        result=api.BlastJobResult(job_id="blast"),
    )
    monkeypatch.setattr(http_jobs, "_MAX_ANALYSIS_LOGS", 2)
    monkeypatch.setattr(http_jobs, "_MAX_BLAST_LOGS", 2)

    api._append_job_log_locked(analysis, "")
    api._append_blast_log_locked(blast, "")
    for message in ("one", "two", "three"):
        api._append_job_log_locked(analysis, message)
        api._append_blast_log_locked(blast, message)

    assert [entry.message for entry in analysis.result.logs] == ["two", "three"]
    assert [entry.message for entry in blast.result.logs] == ["two", "three"]
    analysis_copy = api._job_snapshot(analysis)
    blast_copy = api._blast_job_snapshot(blast)
    analysis_copy.detail = "changed"
    blast_copy.detail = "changed"
    assert analysis.result.detail is None
    assert blast.result.detail is None

    with pytest.raises(api.HTTPException) as analysis_error:
        api.get_analysis_job("missing")
    with pytest.raises(api.HTTPException) as blast_error:
        api.get_blast_job("missing")
    with pytest.raises(api.HTTPException):
        with api._blast_jobs_lock:
            api._blast_jobs["wrong"] = blast
        api.get_blast_job("wrong", command="different")
    with api._blast_jobs_lock:
        api._blast_jobs.pop("wrong", None)
    assert analysis_error.value.status_code == 404
    assert blast_error.value.status_code == 404


@pytest.mark.parametrize(
    ("command", "cancel", "wakes_choice"),
    [
        ("blast_from_the_past", api.cmd_cancel_blast_job, False),
        ("daily_mind_radio", api.cmd_cancel_daily_mind_radio_job, False),
        ("flush_new_kids", api.cmd_cancel_new_kids_job, True),
        ("flush_queue_2", api.cmd_cancel_queue_2_job, True),
        ("flush_queue_3", api.cmd_cancel_queue_3_job, True),
        ("flush_new_wine", api.cmd_cancel_new_wine_job, True),
        ("flush_slow_listening", api.cmd_cancel_slow_listening_job, True),
        ("something_old", api.cmd_cancel_something_old_job, True),
        ("check_new_releases", api.cmd_cancel_release_check_job, True),
        ("plan_discographies", api.cmd_cancel_discography_job, True),
        (
            "flush_requeue_for_a_dream",
            api.cmd_cancel_requeue_for_a_dream_job,
            False,
        ),
        ("fill_palace_of_memory", api.cmd_cancel_palace_of_memory_job, False),
        (
            "update_scrobble_history",
            api.cmd_cancel_scrobble_history_job,
            False,
        ),
    ],
)
def test_playlist_job_cancellation_is_consistent(
    command: str,
    cancel,
    wakes_choice: bool,
) -> None:
    job_id = f"job-{command}"
    job = api._BlastJob(
        result=api.BlastJobResult(
            job_id=job_id,
            command=command,
            status="waiting",
        )
    )
    with api._blast_jobs_lock:
        api._blast_jobs[job_id] = job

    snapshot = cancel(job_id)

    assert snapshot.status == "cancelling"
    assert snapshot.detail
    assert snapshot.logs[-1].message == snapshot.detail
    assert job.cancel_event.is_set()
    assert job.choice_event.is_set() is wakes_choice
    with api._blast_jobs_lock:
        api._blast_jobs.pop(job_id, None)


@pytest.mark.parametrize(
    ("command", "cancel"),
    [
        ("blast_from_the_past", api.cmd_cancel_blast_job),
        ("daily_mind_radio", api.cmd_cancel_daily_mind_radio_job),
        ("flush_new_kids", api.cmd_cancel_new_kids_job),
        ("flush_queue_2", api.cmd_cancel_queue_2_job),
        ("flush_queue_3", api.cmd_cancel_queue_3_job),
        ("flush_new_wine", api.cmd_cancel_new_wine_job),
        ("flush_slow_listening", api.cmd_cancel_slow_listening_job),
        ("something_old", api.cmd_cancel_something_old_job),
        ("check_new_releases", api.cmd_cancel_release_check_job),
        ("plan_discographies", api.cmd_cancel_discography_job),
        ("flush_requeue_for_a_dream", api.cmd_cancel_requeue_for_a_dream_job),
        ("fill_palace_of_memory", api.cmd_cancel_palace_of_memory_job),
        ("update_scrobble_history", api.cmd_cancel_scrobble_history_job),
    ],
)
def test_completed_playlist_jobs_cannot_be_cancelled(command: str, cancel) -> None:
    job_id = f"completed-{command}"
    with api._blast_jobs_lock:
        api._blast_jobs[job_id] = api._BlastJob(
            result=api.BlastJobResult(
                job_id=job_id,
                command=command,
                status="completed",
            )
        )

    with pytest.raises(api.HTTPException) as exc:
        cancel(job_id)

    assert exc.value.status_code == 409
    with api._blast_jobs_lock:
        api._blast_jobs.pop(job_id, None)


def test_analysis_job_cancellation_and_inactive_rejection() -> None:
    active = api._AnalysisJob(
        result=api.AnalysisJobResult(
            job_id="active-analysis",
            command="sync",
            status="running",
            resources={},
        ),
        cancel_event=Event(),
    )
    inactive = api._AnalysisJob(
        result=api.AnalysisJobResult(
            job_id="inactive-analysis",
            command="sync",
            status="completed",
            resources={},
        ),
        cancel_event=Event(),
    )
    with api._analysis_jobs_lock:
        api._analysis_jobs["active-analysis"] = active
        api._analysis_jobs["inactive-analysis"] = inactive

    snapshot = api.cmd_cancel_library_analysis_job("active-analysis")

    assert snapshot.status == "cancelling"
    assert active.cancel_event.is_set()
    assert snapshot.logs[-1].message.startswith("Cancellation requested")
    with pytest.raises(api.HTTPException) as exc:
        api.cmd_cancel_library_analysis_job("inactive-analysis")
    assert exc.value.status_code == 409
    with api._analysis_jobs_lock:
        api._analysis_jobs.pop("active-analysis", None)
        api._analysis_jobs.pop("inactive-analysis", None)


def test_server_file_status_reports_stat_failure() -> None:
    class UnreadablePath:
        name = "mirror.json"

        @staticmethod
        def stat() -> None:
            raise OSError("permission denied")

    with pytest.raises(api.HTTPException) as exc:
        api._server_file_status(UnreadablePath())  # type: ignore[arg-type]
    assert exc.value.status_code == 500
    assert "mirror.json" in exc.value.detail


@pytest.mark.parametrize(
    "path",
    [
        "/commands/blast-from-the-past",
        "/commands/blast-from-the-past-artists",
        "/commands/daily-mind-radio",
        "/commands/found-art",
        "/commands/fill-queue-from-lastfm",
        "/commands/flush-queue",
        "/commands/flush-new-kids",
        "/commands/flush-queue-2",
        "/commands/flush-queue-3",
        "/commands/flush-new-wine",
        "/commands/flush-slow-listening",
        "/commands/something-old",
        "/commands/check-new-releases",
        "/commands/plan-discographies",
        "/commands/flush-requeue-for-a-dream",
        "/commands/fill-palace-of-memory",
        "/commands/update-scrobble-history",
    ],
)
def test_routine_endpoints_report_missing_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    settings = SimpleNamespace(
        blast_from_the_past_playlist=None,
        daily_mind_radio_playlist=None,
        found_art_playlist=None,
        lastfm_api_key=None,
        lastfm_username=None,
        the_queue_playlist=None,
        new_kids_on_the_block_playlist=None,
        the_queue_2_playlist=None,
        the_queue_3_playlist=None,
        great_discoveries_2026_playlist=None,
        unlucky_ones_playlist=None,
        discography_newfoundland_playlist=None,
        discography_memory_lane_playlist=None,
        discography_requeue_playlist=None,
        new_wine_from_old_bottles_playlist=None,
        sauvignon_terre_neuve_playlist=None,
        wine_cellar_playlist=None,
        slow_listening_playlist=None,
        something_old_new_playlist=None,
        new_vintage_playlist=None,
        reqeueue_for_a_dream_playlist=None,
        palace_of_memory_playlist=None,
    )
    monkeypatch.setattr(http_jobs, "Settings", lambda: settings)

    response = client.post(path)

    assert response.status_code == 500
    assert "not configured" in response.json()["detail"].casefold()


def test_blast_from_the_past_endpoint_runs_background_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blast from the past endpoint runs background job.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = BlastFromThePastEndpointRunsBackgroundJobScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                blast_from_the_past_playlist="spotify:playlist:blast"
            )
        ),
    )
    monkeypatch.setattr(
        api.blast_from_past, "add_blast_from_past_to_spotify", scenario.complete
    )
    response = client.post("/commands/blast-from-the-past")
    assert response.status_code == 202
    result = wait_for_blast_status(client, response.json()["job_id"], {"completed"})
    scenario._assert_result(result)


def test_blast_from_the_past_endpoint_rejects_both_limits(
    client: TestClient,
) -> None:
    response = client.post(
        "/commands/blast-from-the-past",
        params={"count": 2, "max_playlist_length": 10},
    )

    assert response.status_code == 400
    assert "either count or max_playlist_length" in response.json()["detail"]


def test_blast_from_the_past_artists_endpoint_runs_background_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blast from the past artists endpoint runs background job.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    scenario = BlastFromThePastArtistsEndpointRunsBackgroundJobScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(return_value=SimpleNamespace(blast_from_the_past_playlist="blast")),
    )
    monkeypatch.setattr(
        api.blast_from_past_artists,
        "add_dormant_artists_to_blast_from_past",
        scenario.complete,
    )
    response = client.post("/commands/blast-from-the-past-artists")
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    deadline = monotonic() + 2
    result = None
    while monotonic() < deadline:
        polled = client.get(f"/commands/blast-from-the-past-artists-jobs/{job_id}")
        assert polled.status_code == 200
        if polled.json()["status"] == "completed":
            result = polled.json()
            break
        sleep(0.01)
    scenario._assert_result(result)


def test_daily_mind_radio_endpoint_runs_background_job(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daily mind radio endpoint runs background job.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scrobble = api.blast_from_past.Scrobble(
        track="Track", artist="Artist", album="Album", timestamp_ms=1
    )
    selection = api.blast_from_past.ScrobbleSelection(
        selected_date=date(2025, 7, 22),
        date_index=0,
        scrobbles_on_date=20,
        page=1,
        total_pages=1,
        direction="top down",
        position=3,
        scrobble=scrobble,
    )
    match = api.blast_from_past.SpotifyTrackMatch(
        spotify_id="track-id",
        uri="spotify:track:track-id",
        track="Track",
        artists=("Artist",),
        album="Album",
        search_rank=1,
        track_similarity=1.0,
        album_similarity=1.0,
        popularity=20,
        liked=False,
    )
    batch = api.daily_mind_radio.DailyMindRadioBatch(
        generated_at=datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
        target_dates=(date(2025, 7, 22), date(2020, 7, 22)),
        missing_dates=(date(2020, 7, 22),),
        selections=(selection,),
    )
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                daily_mind_radio_playlist="spotify:playlist:daily"
            )
        ),
    )
    scenario = DailyMindRadioEndpointRunsBackgroundJobScenario(
        batch=batch, match=match, selection=selection
    )
    monkeypatch.setattr(
        api.daily_mind_radio, "add_daily_mind_radio_to_spotify", scenario.complete
    )
    response = client.post("/commands/daily-mind-radio")
    assert response.status_code == 202
    result = wait_for_daily_mind_radio_status(
        client, response.json()["job_id"], {"completed"}
    )
    assert result["command"] == "daily_mind_radio"
    assert result["dry_run"] is True
    assert result["added"] == 1
    assert result["playlist_length_before"] == 2
    assert result["playlist_length_after"] == 2
    assert result["detail"].startswith("Would add 1")
    assert result["target_dates"] == ["2025-07-22", "2020-07-22"]
    assert result["missing_dates"] == ["2020-07-22"]
    assert result["random_org_timestamp"] == "2026-07-22T13:00:52+00:00"
    assert result["selections"][0]["selected_date"] == "2025-07-22"
    assert any(
        entry["message"] == "Searching Spotify track 1/1" for entry in result["logs"]
    )


def test_active_daily_mind_radio_job_can_be_restored(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Active daily mind radio job can be restored.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    release = api.Event()
    batch = api.daily_mind_radio.DailyMindRadioBatch(
        generated_at=None,
        target_dates=(date(2025, 7, 22),),
        missing_dates=(date(2025, 7, 22),),
        selections=(),
    )
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(return_value=SimpleNamespace(daily_mind_radio_playlist="daily")),
    )
    scenario = ActiveDailyMindRadioJobCanBeRestoredScenario(
        batch=batch, release=release
    )
    monkeypatch.setattr(
        api.daily_mind_radio, "add_daily_mind_radio_to_spotify", scenario.blocked
    )
    started = client.post("/commands/daily-mind-radio")
    active = client.get("/commands/daily-mind-radio-jobs")
    duplicate = client.post("/commands/daily-mind-radio")
    release.set()
    assert started.status_code == 202
    assert [job["job_id"] for job in active.json()] == [started.json()["job_id"]]
    assert client.get("/commands/blast-from-the-past-jobs").json() == []
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["command"] == "daily_mind_radio"
    wait_for_daily_mind_radio_status(client, started.json()["job_id"], {"completed"})
    assert client.get("/commands/daily-mind-radio-jobs").json() == []


def test_found_art_endpoint_runs_background_job_with_requested_count(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found art endpoint runs background job with requested count.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    received = {}
    candidate = api.found_art.FoundArtCandidate(
        artist="Recommendation Artist",
        track="Recommendation Track",
        key=("recommendation artist", "recommendation track"),
        score=1.25,
        best_match=0.9,
        supporting_seeds=("Seed Artist - Seed Track",),
        base_rank=4,
        weekly_rank=0.75,
    )
    match = api.blast_from_past.SpotifyTrackMatch(
        spotify_id="recommendation-id",
        uri="spotify:track:recommendation-id",
        track="Recommendation Track",
        artists=("Recommendation Artist",),
        album="Recommendation Album",
        search_rank=1,
        track_similarity=1.0,
        album_similarity=None,
        popularity=42,
        liked=False,
    )
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                found_art_playlist="spotify:playlist:found",
                lastfm_api_key="lastfm-key",
                lastfm_username="lastfm-user",
            )
        ),
    )
    scenario = FoundArtEndpointRunsBackgroundJobWithRequestedCountScenario(
        candidate=candidate, match=match, received=received
    )
    monkeypatch.setattr(api.found_art, "run_found_art", scenario.complete)
    response = client.post("/commands/found-art", params={"count": 7})
    assert response.status_code == 202
    result = wait_for_found_art_status(client, response.json()["job_id"], {"completed"})
    assert received["playlist_id"] == "found"
    assert received["count"] == 7
    assert received["lastfm"].api_key == "lastfm-key"
    assert received["lastfm"].username == "lastfm-user"
    assert result["command"] == "found_art"
    assert result["requested_count"] == 7
    assert result["added"] == 1
    assert result["week_start"] == "2026-07-17"
    assert result["history_scrobbles"] == 250
    assert result["candidate_count"] == 50
    assert result["found_art_results"][0]["artist"] == "Recommendation Artist"
    assert (
        result["found_art_results"][0]["spotify_match"]
        == "Recommendation Artist - Recommendation Track - Recommendation Album"
    )
    assert any(
        entry["message"] == "Getting Last.fm neighbors for seed 1/1"
        for entry in result["logs"]
    )


def test_sauvignon_web_job_waits_for_album_choice_and_completes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sauvignon web job waits for album choice and completes.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    scenario = SauvignonWebJobWaitsForAlbumChoiceAndCompletesScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                sauvignon_terre_neuve_playlist="spotify:playlist:sauvignon",
                lastfm_api_key="lastfm-key",
                lastfm_username="lastfm-user",
            )
        ),
    )
    monkeypatch.setattr(
        api.sauvignon,
        "fill_sauvignon_from_lastfm",
        FeatureInvocation(scenario, ("playlist_id",)),
    )
    response = client.post(
        "/commands/fill-sauvignon-from-lastfm", params={"dry_run": True}
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    waiting = wait_for_sauvignon_status(client, job_id, {"waiting"})
    scenario._assert_waiting(client, job_id, waiting)
    choice = client.post(
        f"/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "alternate"},
    )
    assert choice.status_code == 200
    result = wait_for_sauvignon_status(client, job_id, {"completed"})
    scenario._assert_result(client, result)


def test_sauvignon_endpoint_validates_limits_and_configuration(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conflict = client.post(
        "/commands/fill-sauvignon-from-lastfm",
        params={"count": 2, "max_playlist_length": 20},
    )
    assert conflict.status_code == 400

    monkeypatch.setattr(
        http_jobs,
        "Settings",
        lambda: SimpleNamespace(
            sauvignon_terre_neuve_playlist=None,
            lastfm_api_key="key",
            lastfm_username="user",
        ),
    )
    missing = client.post("/commands/fill-sauvignon-from-lastfm")
    assert missing.status_code == 500
    assert "SAUVIGNON_TERRE_NEUVE_PLAYLIST" in missing.json()["detail"]


def test_new_kids_web_job_waits_for_and_applies_release_choice(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New kids web job waits for and applies release choice.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = NewKidsWebJobWaitsForAndAppliesReleaseChoiceScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                new_kids_on_the_block_playlist="spotify:playlist:newkids",
                the_queue_2_playlist="spotify:playlist:queue2",
                great_discoveries_2026_playlist="spotify:playlist:great",
                unlucky_ones_playlist="spotify:playlist:unlucky",
                discography_newfoundland_playlist="spotify:playlist:newfoundland",
                lastfm_api_key="lastfm-key",
                lastfm_username="lastfm-user",
            )
        ),
    )
    monkeypatch.setattr(
        api.new_kids,
        "flush_new_kids",
        FeatureInvocation(
            scenario,
            (
                "new_kids_playlist_id",
                "queue_2_playlist_id",
                "great_discoveries_playlist_id",
                "unlucky_ones_playlist_id",
                "newfoundland_playlist_id",
            ),
        ),
    )
    started = client.post("/commands/flush-new-kids", params={"dry_run": "true"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_new_kids_status(client, job_id, {"waiting"})
    scenario._assert_waiting(client, job_id, waiting)
    choice = client.post(
        f"/commands/flush-new-kids-jobs/{job_id}/choice", json={"choice": "release"}
    )
    assert choice.status_code == 200
    completed = wait_for_new_kids_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_queue_fill_web_job_waits_for_artist_mapping(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queue fill web job waits for artist mapping.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    scenario = QueueFillWebJobWaitsForArtistMappingScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                the_queue_playlist="spotify:playlist:queue",
                the_queue_2_playlist="spotify:playlist:queue2",
                new_kids_on_the_block_playlist="spotify:playlist:newkids",
                the_queue_3_playlist="spotify:playlist:queue3",
                unlucky_ones_playlist="spotify:playlist:unlucky",
                lastfm_api_key="lastfm-key",
                lastfm_username="lastfm-user",
            )
        ),
    )
    monkeypatch.setattr(
        api.the_queue,
        "fill_queue_from_lastfm",
        FeatureInvocation(scenario, ("playlists",)),
    )
    started = client.post(
        "/commands/fill-queue-from-lastfm",
        params={"count": 2, "seed_count": 30, "dry_run": "true"},
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_queue_fill_status(client, job_id, {"waiting"})
    scenario._assert_waiting(client, job_id, waiting)
    unavailable = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "missing-artist"},
    )
    empty_search = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "search:   "},
    )
    scenario._assert_empty_search(empty_search, unavailable)
    choice = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "artist-id"},
    )
    assert choice.status_code == 200
    completed = wait_for_queue_fill_status(client, job_id, {"completed"})
    scenario._assert_completed(completed)
    stale_choice = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "artist-id"},
    )
    scenario._assert_stale_choice(client, stale_choice)


def test_queue_fill_rejects_count_and_playlist_cap_together(
    client: TestClient,
) -> None:
    response = client.post(
        "/commands/fill-queue-from-lastfm",
        params={"count": 1, "max_playlist_length": 10},
    )

    assert response.status_code == 400
    assert "either count or maximum" in response.json()["detail"]


def test_queue_flush_web_job_returns_live_decisions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queue flush web job returns live decisions.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    received: dict[str, object] = {}
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                the_queue_playlist="spotify:playlist:queue",
                the_queue_2_playlist="spotify:playlist:queue2",
                new_kids_on_the_block_playlist="spotify:playlist:newkids",
                the_queue_3_playlist="spotify:playlist:queue3",
                unlucky_ones_playlist="spotify:playlist:unlucky",
            )
        ),
    )
    scenario = QueueFlushWebJobReturnsLiveDecisionsScenario(received=received)
    monkeypatch.setattr(api.the_queue, "flush_queue", scenario.flush)
    started = client.post("/commands/flush-queue", params={"dry_run": "true"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    completed = wait_for_queue_flush_status(client, job_id, {"completed"})
    assert received == {
        "spotify_type": "FakeSpotify",
        "queue": "queue",
        "dry_run": True,
    }
    assert completed["run_id"] == "queue-run"
    assert completed["queue_resumed"] is True
    assert completed["queue_flush_results"][0]["target_release"] == "Established Album"
    assert completed["queue_flush_results"][0]["top_liked_tracks"] == 5
    assert client.get("/commands/flush-queue-jobs").json() == []


def test_queue_2_web_job_waits_for_and_applies_release_choice(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queue 2 should expose its shared release prompt and both list counts."""
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    release = api.new_kids.RankedRelease(
        spotify_id="release",
        uri="spotify:album:release",
        name="Ranked Album",
        release_type="Album",
        release_date="2024-01-01",
        total_tracks=9,
        primary_artist_id="artist",
        primary_artist_name="Artist",
        popularity=73,
        top_track_rank=2,
        tier=0,
        identity="ranked album",
        saved=True,
        plain=True,
    )
    received: dict[str, object] = {}
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                new_kids_on_the_block_playlist="spotify:playlist:newkids",
                the_queue_2_playlist="spotify:playlist:queue2",
                great_discoveries_2026_playlist="spotify:playlist:great",
                unlucky_ones_playlist="spotify:playlist:unlucky",
                discography_newfoundland_playlist="spotify:playlist:newfoundland",
                lastfm_api_key="lastfm-key",
                lastfm_username="lastfm-user",
            )
        ),
    )
    scenario = Queue2WebJobWaitsForAndAppliesReleaseChoiceScenario(
        received=received, release=release
    )
    monkeypatch.setattr(
        api.new_kids,
        "flush_queue_2",
        FeatureInvocation(
            scenario,
            (
                "new_kids_playlist_id",
                "queue_2_playlist_id",
                "great_discoveries_playlist_id",
                "unlucky_ones_playlist_id",
                "newfoundland_playlist_id",
            ),
        ),
    )
    started = client.post("/commands/flush-queue-2", params={"dry_run": "true"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_queue_2_status(client, job_id, {"waiting"})
    assert waiting["command"] == "flush_queue_2"
    assert waiting["new_kids_pending_choice"]["artist"] == "Artist"
    assert [
        job["job_id"] for job in client.get("/commands/flush-queue-2-jobs").json()
    ] == [job_id]
    choice = client.post(
        f"/commands/flush-queue-2-jobs/{job_id}/choice", json={"choice": "release"}
    )
    assert choice.status_code == 200
    completed = wait_for_queue_2_status(client, job_id, {"completed"})
    assert received == {
        "spotify_type": "FakeSpotify",
        "new_playlist_id": "newkids",
        "queue_playlist_id": "queue2",
        "great_playlist_id": "great",
        "unlucky_playlist_id": "unlucky",
        "newfoundland_playlist_id": "newfoundland",
        "dry_run": True,
        "choice": "release",
    }
    assert completed["playlist_length_before"] == 20
    assert completed["playlist_length_after"] == 19
    assert completed["new_kids_resumed"] is True
    assert completed["new_kids_results"][0]["target_track"] == "Opening Track"
    assert completed["new_kids_prefill"][0]["artist"] == "First Artist"
    assert "New Kids 9 -> 10; Queue 2 20 -> 19" in completed["detail"]
    assert client.get("/commands/flush-queue-2-jobs").json() == []


def test_queue_3_web_job_handles_release_and_composer_choices(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Queue 3 should reconnect across both of its interactive choice types."""
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = Queue3WebJobHandlesReleaseAndComposerChoicesScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(the_queue_3_playlist="spotify:playlist:queue3")
        ),
    )
    monkeypatch.setattr(
        api.queue_3,
        "flush_queue_3",
        FeatureInvocation(scenario, ("playlist_id", "transition_reader")),
    )
    started = client.post("/commands/flush-queue-3", params={"dry_run": "true"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    release_wait = wait_for_queue_3_choice(client, job_id, "release")
    scenario._assert_release_wait(client, job_id, release_wait)
    release_response = client.post(
        f"/commands/flush-queue-3-jobs/{job_id}/choice", json={"choice": "advance"}
    )
    assert release_response.status_code == 200
    composer_wait = wait_for_queue_3_choice(client, job_id, "composer_playlist")
    assert [
        playlist["spotify_id"]
        for playlist in composer_wait["queue_3_pending_choice"]["playlists"]
    ] == ["bach-a", "bach-b"]
    composer_response = client.post(
        f"/commands/flush-queue-3-jobs/{job_id}/choice", json={"choice": "bach-b"}
    )
    assert composer_response.status_code == 200
    completed = wait_for_queue_3_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_queue_3_previous_year_import_has_a_separate_web_action(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The annual-only job should import without invoking the Queue 3 flush."""
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    received: dict[str, object] = {}
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(the_queue_3_playlist="spotify:playlist:queue3")
        ),
    )
    scenario = Queue3PreviousYearImportHasASeparateWebActionScenario(received=received)
    monkeypatch.setattr(
        api.queue_3, "import_previous_year_discoveries", scenario.import_previous_year
    )
    monkeypatch.setattr(
        api.queue_3,
        "flush_queue_3",
        FeatureInvocation(
            UnexpectedInteraction("Queue 3 flush must not run"),
            ("playlist_id", "transition_reader"),
        ),
    )
    started = client.post(
        "/commands/import-queue-3-previous-year", params={"dry_run": "true"}
    )
    assert started.status_code == 202
    assert started.json()["queue_3_annual_only"] is True
    job_id = started.json()["job_id"]
    completed = wait_for_queue_3_status(client, job_id, {"completed"})
    assert received == {
        "spotify_type": "FakeSpotify",
        "playlist_id": "queue3",
        "dry_run": True,
    }
    assert completed["queue_3_annual_only"] is True
    assert completed["queue_3_annual_import"][0]["artist"] == "Imported Artist"
    assert completed["added"] == 1
    assert "1 artist would be added; 2 already present" in completed["detail"]
    assert any(
        entry["message"] == "Annual import checked" for entry in completed["logs"]
    )


def test_new_wine_web_job_waits_for_and_applies_release_choice(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New wine web job waits for and applies release choice.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = NewWineWebJobWaitsForAndAppliesReleaseChoiceScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                new_wine_from_old_bottles_playlist="spotify:playlist:new",
                sauvignon_terre_neuve_playlist="spotify:playlist:sauv",
                wine_cellar_playlist="spotify:playlist:cellar",
            )
        ),
    )
    monkeypatch.setattr(api.new_wine, "flush_new_wine", WineInvocation(scenario))
    started = client.post(
        "/commands/flush-new-wine", params={"dry_run": "true", "no_discovery": "true"}
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_new_wine_status(client, job_id, {"waiting"})
    scenario._assert_waiting(client, job_id, waiting)
    choice = client.post(
        f"/commands/flush-new-wine-jobs/{job_id}/choice", json={"choice": "alternative"}
    )
    assert choice.status_code == 200
    completed = wait_for_new_wine_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_new_wine_web_job_accepts_canonical_album_endpoint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """New wine web job accepts canonical album endpoint.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    release = api.new_wine.ReleaseCandidate(
        spotify_id="album",
        uri="spotify:album:album",
        name="Deluxe Album",
        release_type="Album",
        release_date="2026-01-01",
        total_tracks=8,
        primary_artist_id="artist",
        primary_artist_name="Artist",
    )
    source = api.new_wine.PlaylistTrack(
        spotify_id="track",
        uri="spotify:track:track",
        name="Canonical Finale",
        primary_artist_id="artist",
        primary_artist_name="Artist",
        release=release,
    )
    tracks = tuple(
        api.new_wine.ReleaseTrack(
            spotify_id=f"t{index}",
            uri=f"spotify:track:t{index}",
            name=f"Track {index}",
            disc_number=1,
            track_number=index,
        )
        for index in range(1, 9)
    )
    received: dict[str, object] = {}
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                new_wine_from_old_bottles_playlist="new",
                sauvignon_terre_neuve_playlist="sauv",
                wine_cellar_playlist="cellar",
            )
        ),
    )
    scenario = NewWineWebJobAcceptsCanonicalAlbumEndpointScenario(
        received=received, source=source, tracks=tracks
    )
    monkeypatch.setattr(api.new_wine, "flush_new_wine", WineInvocation(scenario))
    started = client.post(
        "/commands/flush-new-wine",
        params={"dry_run": "true", "choose_album_endpoints": "true"},
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_new_wine_status(client, job_id, {"waiting"})
    assert waiting["choose_album_endpoints"] is True
    assert waiting["pending_choice"] == {
        "kind": "album_endpoint",
        "artist": "Artist",
        "source_track": "Canonical Finale",
        "release": "Deluxe Album",
        "track_position": 5,
        "total_tracks": 8,
        "terminal_release": False,
        "releases": [],
    }
    response = client.post(
        f"/commands/flush-new-wine-jobs/{job_id}/choice",
        json={"choice": api.new_wine.CHOICE_CUTOFF},
    )
    assert response.status_code == 200
    completed = wait_for_new_wine_status(client, job_id, {"completed"})
    assert received == {"enabled": True, "choice": api.new_wine.CHOICE_CUTOFF}
    assert completed["new_wine_results"][0]["canonical_track_count"] == 5
    assert (
        completed["new_wine_results"][0]["canonical_cutoff_track"] == "Canonical Finale"
    )


def test_new_wine_web_job_accepts_finish_at_album_endpoint(
    client: TestClient,
) -> None:
    from spotify_manager import api

    job_id = "new-wine-finish"
    pending = api.NewWinePendingChoice(
        artist="Artist",
        source_track="Last Track",
        terminal_release=True,
        releases=[
            api.NewWineReleaseOption(
                spotify_id="follow-up",
                name="Follow-up Album",
                release_type="Album",
                release_date="2026-06-01",
                total_tracks=8,
                primary_artist_name="Artist",
            )
        ],
    )
    with api._blast_jobs_lock:
        api._blast_jobs[job_id] = api._BlastJob(
            result=api.BlastJobResult(
                job_id=job_id,
                command="flush_new_wine",
                status="waiting",
                pending_choice=pending,
            )
        )

    response = client.post(
        f"/commands/flush-new-wine-jobs/{job_id}/choice",
        json={"choice": api.new_wine.CHOICE_FINISH},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    with api._blast_jobs_lock:
        job = api._blast_jobs[job_id]
        assert job.submitted_choice == api.new_wine.CHOICE_FINISH
        assert job.choice_event.is_set()


def test_new_wine_web_job_rejects_finish_before_an_endpoint(
    client: TestClient,
) -> None:
    from spotify_manager import api

    job_id = "new-wine-premature-finish"
    pending = api.NewWinePendingChoice(
        artist="Artist",
        source_track="Single",
        terminal_release=False,
    )
    with api._blast_jobs_lock:
        api._blast_jobs[job_id] = api._BlastJob(
            result=api.BlastJobResult(
                job_id=job_id,
                command="flush_new_wine",
                status="waiting",
                pending_choice=pending,
            )
        )

    response = client.post(
        f"/commands/flush-new-wine-jobs/{job_id}/choice",
        json={"choice": api.new_wine.CHOICE_FINISH},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "release choice is not available"


def test_slow_listening_web_job_handles_all_interactive_choices(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slow listening web job handles all interactive choices.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = SlowListeningWebJobHandlesAllInteractiveChoicesScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                slow_listening_playlist="spotify:playlist:slow"
            )
        ),
    )
    monkeypatch.setattr(api.slow_listening, "flush_slow_listening", scenario.flush)
    started = client.post("/commands/flush-slow-listening", params={"dry_run": "false"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    track_waiting = wait_for_slow_listening_status(client, job_id, {"waiting"})
    scenario._assert_track_waiting(client, job_id, track_waiting)
    track_choice = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={"choice": "advance"},
    )
    assert track_choice.status_code == 200
    order_waiting = wait_for_slow_listening_status(client, job_id, {"waiting"})
    pending_order = order_waiting["slow_listening_pending_choice"]
    scenario._assert_pending_order(pending_order)
    invalid_order = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={"choice": "order", "order": ["first-release", "first-release"]},
    )
    assert invalid_order.status_code == 400
    order_choice = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={"choice": "order", "order": ["second-release", "first-release"]},
    )
    assert order_choice.status_code == 200
    completion_waiting = wait_for_slow_listening_status(client, job_id, {"waiting"})
    assert completion_waiting["slow_listening_pending_choice"]["kind"] == "completion"
    completion_choice = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={"choice": "continue"},
    )
    assert completion_choice.status_code == 200
    completed = wait_for_slow_listening_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_slow_listening_web_job_retries_a_connection_reset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Slow listening web job retries a connection reset.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    attempts = 0
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                slow_listening_playlist="spotify:playlist:slow"
            )
        ),
    )
    monkeypatch.setattr(SlowListeningWorker, "sleep", Mock(return_value=None))
    scenario = SlowListeningWebJobRetriesAConnectionResetScenario(attempts=attempts)
    monkeypatch.setattr(api.slow_listening, "flush_slow_listening", scenario.flush)
    started = client.post("/commands/flush-slow-listening", params={"dry_run": "true"})
    assert started.status_code == 202
    completed = wait_for_slow_listening_status(
        client, started.json()["job_id"], {"completed"}
    )
    assert scenario.attempts == 2
    assert (
        completed["detail"]
        == "0/0 processed; 0 advanced, 0 artists completed, 0 skipped."
    )
    assert any(
        entry["message"].startswith(
            "Spotify connection interrupted while loading the Slow Listening "
            "playlist. Retrying in 10 seconds (at "
        )
        for entry in completed["logs"]
    )


def test_something_old_web_job_handles_all_interactive_choices(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Something old web job handles all interactive choices.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = SomethingOldWebJobHandlesAllInteractiveChoicesScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                something_old_new_playlist="spotify:playlist:0000000000000000000000",
                lastfm_api_key="lastfm-key",
                lastfm_username="man-et-arms",
            )
        ),
    )
    monkeypatch.setattr(
        api.something_old,
        "run_something_old",
        FeatureInvocation(scenario, ("playlist_id",)),
    )
    started = client.post("/commands/something-old", params={"dry_run": "true"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    artist_waiting = wait_for_something_old_status(client, job_id, {"waiting"})
    scenario._assert_artist_waiting(artist_waiting, client, job_id)
    invalid_artist = client.post(
        f"/commands/something-old-jobs/{job_id}/choice",
        json={"choice": "not-an-artist"},
    )
    assert invalid_artist.status_code == 400
    artist_choice = client.post(
        f"/commands/something-old-jobs/{job_id}/choice", json={"choice": "artist-one"}
    )
    assert artist_choice.status_code == 200
    mode_waiting = wait_for_something_old_status(client, job_id, {"waiting"})
    scenario._assert_mode_waiting(mode_waiting)
    mode_choice = client.post(
        f"/commands/something-old-jobs/{job_id}/choice", json={"choice": "album"}
    )
    assert mode_choice.status_code == 200
    album_waiting = wait_for_something_old_status(client, job_id, {"waiting"})
    pending_album = album_waiting["something_old_pending_choice"]
    scenario._assert_pending_album(pending_album)
    album_choice = client.post(
        f"/commands/something-old-jobs/{job_id}/choice", json={"choice": "release-id"}
    )
    assert album_choice.status_code == 200
    completed = wait_for_something_old_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_release_check_web_job_handles_search_mapping_and_release_choice(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release check web job handles search mapping and release choice.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = ReleaseCheckWebJobHandlesSearchMappingAndReleaseChoiceScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                wine_cellar_playlist="spotify:playlist:0000000000000000000001",
                new_vintage_playlist="spotify:playlist:0000000000000000000002",
                lastfm_api_key="lastfm-key",
                lastfm_username="man-et-arms",
            )
        ),
    )
    monkeypatch.setattr(
        api.release_check,
        "run_release_check",
        FeatureInvocation(scenario, ("playlists",)),
    )
    started = client.post("/commands/check-new-releases", params={"dry_run": "true"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    first_mapping = wait_for_release_check_status(client, job_id, {"waiting"})
    scenario._assert_first_mapping(client, first_mapping, job_id)
    searched = client.post(
        f"/commands/check-new-releases-jobs/{job_id}/choice",
        json={"choice": "search:Lastfm Artist Band"},
    )
    assert searched.status_code == 200
    second_mapping = wait_for_release_check_status(client, job_id, {"waiting"})
    scenario._assert_second_mapping(client, job_id, second_mapping)
    release_waiting = wait_for_release_check_status(client, job_id, {"waiting"})
    pending = release_waiting["release_check_pending_choice"]
    scenario._assert_pending(client, job_id, pending)
    completed = wait_for_release_check_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_discography_web_job_collects_releases_and_confirms_removal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discography web job collects releases and confirms removal.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = DiscographyWebJobCollectsReleasesAndConfirmsRemovalScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                discography_newfoundland_playlist="nf",
                discography_memory_lane_playlist="ml",
                discography_requeue_playlist="rq",
                the_queue_3_playlist="q3",
            )
        ),
    )
    monkeypatch.setattr(api.discography, "build_discography_plan", scenario.build)
    monkeypatch.setattr(api.discography, "apply_discography_plan", scenario.apply)
    started = client.post("/commands/plan-discographies", params={"dry_run": "false"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_discography_status(client, job_id, {"waiting"})
    artist_pending = waiting["discography_pending_choice"]
    scenario._assert_artist_pending(artist_pending, client, job_id)
    waiting = wait_for_discography_status(client, job_id, {"waiting"})
    pending = waiting["discography_pending_choice"]
    scenario._assert_pending(client, job_id, pending)
    submitted = client.post(
        f"/commands/plan-discographies-jobs/{job_id}/choice",
        json={"choice": "select", "release_ids": ["studio", "live"]},
    )
    assert submitted.status_code == 200
    confirmation = wait_for_discography_status(client, job_id, {"waiting"})
    scenario._assert_confirmation(confirmation)
    confirmed = client.post(
        f"/commands/plan-discographies-jobs/{job_id}/choice", json={"choice": "apply"}
    )
    assert confirmed.status_code == 200
    completed = wait_for_discography_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_requeue_for_a_dream_web_job_reports_transition_and_reconnects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requeue for a dream web job reports transition and reconnects.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = RequeueForADreamWebJobReportsTransitionAndReconnectsScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                reqeueue_for_a_dream_playlist="spotify:playlist:0000000000000000000000"
            )
        ),
    )
    monkeypatch.setattr(
        api.requeue_for_a_dream, "flush_requeue_for_a_dream", scenario.run
    )
    started = client.post(
        "/commands/flush-requeue-for-a-dream", params={"dry_run": "true"}
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    scenario._assert_job_id(client, job_id)
    scenario.release_worker.set()
    completed = wait_for_requeue_for_a_dream_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_palace_of_memory_web_job_reports_results_and_reconnects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Palace of memory web job reports results and reconnects.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = PalaceOfMemoryWebJobReportsResultsAndReconnectsScenario.example()
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                palace_of_memory_playlist="spotify:playlist:0000000000000000000000"
            )
        ),
    )
    monkeypatch.setattr(
        api.palace_of_memory,
        "fill_palace_of_memory",
        FeatureInvocation(scenario, ("playlist_id",)),
    )
    started = client.post(
        "/commands/fill-palace-of-memory",
        params={"dry_run": "true", "alphabetical_start": "6"},
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    scenario._assert_job_id(client, job_id)
    scenario.release_worker.set()
    completed = wait_for_palace_of_memory_status(client, job_id, {"completed"})
    scenario._assert_completed(client, completed)


def test_palace_web_can_persist_only_cursor_without_playlist_config(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Palace web can persist only cursor without playlist config.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    scenario = PalaceWebCanPersistOnlyCursorWithoutPlaylistConfigScenario()
    monkeypatch.setattr(
        api.palace_of_memory, "set_alphabetical_cursor", scenario.set_cursor
    )
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            side_effect=AssertionError(
                "cursor-only mode must not load playlist settings"
            )
        ),
    )
    started = client.post(
        "/commands/fill-palace-of-memory",
        params={"dry_run": "false", "set_alphabetical_cursor": 250},
    )
    assert started.status_code == 202
    completed = wait_for_palace_of_memory_status(
        client, started.json()["job_id"], {"completed"}
    )
    assert completed["palace_cursor_only"] is True
    assert completed["palace_alphabetical_reference"] == "250"
    assert completed["palace_alphabetical_next_index"] == 249
    assert completed["palace_next_album_artist"] == "Cursor Artist"
    assert completed["palace_next_album"] == "Cursor Album"
    assert completed["playlist_length_before"] is None


def test_scrobble_history_web_job_reports_refresh_summary(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scrobble history web job reports refresh summary.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api
    from spotify_manager.interfaces.http import jobs as http_jobs

    history = tuple(
        api.blast_from_past.Scrobble(
            track="Track", artist="Artist", album="Album", timestamp_ms=index + 1
        )
        for index in range(12)
    )
    received: dict[str, object] = {}
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                lastfm_api_key="lastfm-key", lastfm_username="man-et-arms"
            )
        ),
    )
    scenario = ScrobbleHistoryWebJobReportsRefreshSummaryScenario(
        history=history, received=received
    )
    monkeypatch.setattr(
        api.scrobble_history, "refresh_scrobble_history", scenario.refresh
    )
    started = client.post(
        "/commands/update-scrobble-history", params={"dry_run": "false"}
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    completed = wait_for_scrobble_history_status(client, job_id, {"completed"})
    assert received["expected_username"] == "man-et-arms"
    assert received["dry_run"] is False
    assert completed["history_export_scrobbles"] == 10
    assert completed["history_legacy_scrobbles_added"] == 1
    assert completed["live_scrobbles_added"] == 1
    assert completed["history_scrobbles"] == 12
    assert completed["history_persisted"] is True
    assert completed["history_backup_path"] == "/tmp/scrobbles-backup.json.gz"
    assert any(
        entry["message"] == "Fetching page 1 of 1 from Last.fm"
        for entry in completed["logs"]
    )
    assert client.get("/commands/update-scrobble-history-jobs").json() == []


def wait_for_job_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
    timeout: float = 2,
) -> dict:
    """Poll one fast test job until it reaches an expected state."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        response = client.get(f"/commands/library-analysis-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"job {job_id} did not reach {expected}")


def wait_for_blast_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
    timeout: float = 2,
) -> dict:
    """Poll one fast playlist job until it reaches an expected state."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        response = client.get(f"/commands/blast-from-the-past-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"playlist job {job_id} did not reach {expected}")


def wait_for_daily_mind_radio_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
    timeout: float = 2,
) -> dict:
    """Poll one fast Daily Mind Radio job until it reaches an expected state."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        response = client.get(f"/commands/daily-mind-radio-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Daily Mind Radio job {job_id} did not reach {expected}")


def wait_for_found_art_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
    timeout: float = 2,
) -> dict:
    """Poll one fast Found Art job until it reaches an expected state."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        response = client.get(f"/commands/found-art-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Found Art job {job_id} did not reach {expected}")


def wait_for_sauvignon_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
    timeout: float = 2,
) -> dict:
    """Poll one Sauvignon album-discovery job until it reaches a target state."""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        response = client.get(f"/commands/fill-sauvignon-from-lastfm-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Sauvignon job {job_id} did not reach {expected}")


def wait_for_queue_fill_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Last.fm Queue fill until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/fill-queue-from-lastfm-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Queue fill job {job_id} did not reach {expected}")


def wait_for_queue_flush_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Queue flush until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-queue-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Queue flush job {job_id} did not reach {expected}")


def wait_for_new_wine_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one New Wine job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-new-wine-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"New Wine job {job_id} did not reach {expected}")


def wait_for_new_kids_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one New Kids job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-new-kids-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"New Kids job {job_id} did not reach {expected}")


def wait_for_queue_2_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Queue 2 job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-queue-2-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Queue 2 job {job_id} did not reach {expected}")


def wait_for_queue_3_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Queue 3 job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-queue-3-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Queue 3 job {job_id} did not reach {expected}")


def wait_for_queue_3_choice(
    client: TestClient,
    job_id: str,
    kind: str,
) -> dict:
    """Poll until Queue 3 exposes the requested pending-choice type."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-queue-3-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        pending = body.get("queue_3_pending_choice")
        if body["status"] == "waiting" and pending and pending["kind"] == kind:
            return body
        sleep(0.01)
    pytest.fail(f"Queue 3 job {job_id} did not request {kind}")


def wait_for_slow_listening_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Slow Listening job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-slow-listening-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Slow Listening job {job_id} did not reach {expected}")


def wait_for_something_old_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Something Old job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/something-old-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Something Old job {job_id} did not reach {expected}")


def wait_for_release_check_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one new-release check until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/check-new-releases-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"New-release check {job_id} did not reach {expected}")


def wait_for_discography_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one discography job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/plan-discographies-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Discography job {job_id} did not reach {expected}")


def wait_for_requeue_for_a_dream_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Requeue for a Dream job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/flush-requeue-for-a-dream-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Requeue for a Dream job {job_id} did not reach {expected}")


def wait_for_palace_of_memory_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one Palace job until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/fill-palace-of-memory-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Palace of Memory job {job_id} did not reach {expected}")


def wait_for_scrobble_history_status(
    client: TestClient,
    job_id: str,
    expected: set[str],
) -> dict:
    """Poll one scrobble-history refresh until it reaches an expected state."""
    deadline = monotonic() + 2
    while monotonic() < deadline:
        response = client.get(f"/commands/update-scrobble-history-jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in expected:
            return body
        sleep(0.01)
    pytest.fail(f"Scrobble history job {job_id} did not reach {expected}")


def analysis_summary(mode: str):
    """Build one tiny worker summary."""
    from spotify_manager import api

    return api.library_analysis.LibrarySyncSummary(
        run_id="run-1",
        mode=mode,
        backup_dir=f"/tmp/{mode}/run-1",
        resources=(),
    )


def test_async_analysis_endpoint_runs_background_job_without_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Async analysis endpoint runs background job without client.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api

    scenario = AsyncAnalysisEndpointRunsBackgroundJobWithoutClientScenario()
    monkeypatch.setattr(
        api.library_analysis, "analyse_library_async_routine", scenario.complete_export
    )
    response = client.post("/commands/analyse-library-async")
    assert response.status_code == 202
    body = wait_for_job_status(client, response.json()["job_id"], {"completed"})
    assert body["command"] == "analyse_library_async"
    assert body["run_id"] == "run-1"
    assert body["resources"]["albums"] == {
        "completed": 2,
        "total": 2,
        "status": "Complete",
    }


def test_sync_analysis_endpoint_uses_injected_no_retry_client(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sync analysis endpoint uses injected no retry client.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api

    calls = []
    scenario = SyncAnalysisEndpointUsesInjectedNoRetryClientScenario(calls=calls)
    monkeypatch.setattr(
        api.library_analysis, "analyse_library_sync_routine", scenario.complete_sync
    )
    response = client.post("/commands/analyse-library-sync")
    assert response.status_code == 202
    wait_for_job_status(client, response.json()["job_id"], {"completed"})
    assert len(calls) == 1
    assert isinstance(calls[0], FakeSpotify)
    result = client.get(
        f"/commands/library-analysis-jobs/{response.json()['job_id']}"
    ).json()
    assert any("credentials to app5" in entry["message"] for entry in result["logs"])
    assert result["logs"][-1]["message"].startswith("Analysis completed")


@pytest.mark.parametrize("full_rebuild", [False, True])
def test_live_mirror_refresh_endpoint_skips_artist_progress(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, full_rebuild: bool
) -> None:
    """Live mirror refresh endpoint skips artist progress.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
        full_rebuild: Original full rebuild.
    """
    from spotify_manager import api

    calls = []
    scenario = LiveMirrorRefreshEndpointSkipsArtistProgressScenario(calls=calls)
    monkeypatch.setattr(
        api.library_analysis,
        "refresh_live_library_mirrors_routine",
        scenario.complete_refresh,
    )
    response = client.post(
        "/commands/refresh-library-mirrors",
        params={"full_rebuild": str(full_rebuild).lower()},
    )
    assert response.status_code == 202
    body = wait_for_job_status(client, response.json()["job_id"], {"completed"})
    assert body["command"] == "refresh_library_mirrors"
    assert set(body["resources"]) == {"albums", "tracks"}
    assert body["resources"]["tracks"]["completed"] == 3
    assert body["full_rebuild"] is full_rebuild
    assert len(calls) == 1
    assert isinstance(calls[0][0], FakeSpotify)
    assert calls[0][1] is full_rebuild


@pytest.mark.parametrize(
    ("resource", "requested_full", "expected_full"),
    [
        ("albums", False, False),
        ("tracks", True, True),
        ("artists", False, False),
        ("artists", True, True),
    ],
)
def test_independent_live_mirror_refresh_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    requested_full: bool,
    expected_full: bool,
) -> None:
    """Independent live mirror refresh endpoint.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
        resource: Original resource.
        requested_full: Original requested full.
        expected_full: Original expected full.
    """
    from spotify_manager import api

    calls = []
    scenario = IndependentLiveMirrorRefreshEndpointScenario(calls=calls)
    monkeypatch.setattr(
        api.library_analysis,
        "refresh_live_library_resource_routine",
        scenario.complete_resource,
    )
    response = client.post(
        f"/commands/refresh-library-mirrors/{resource}",
        params={"full_rebuild": str(requested_full).lower()},
    )
    assert response.status_code == 202
    body = wait_for_job_status(client, response.json()["job_id"], {"completed"})
    assert body["command"] == f"refresh_library_mirror_{resource}"
    assert body["mirror_resource"] == resource
    assert set(body["resources"]) == {resource}
    assert body["full_rebuild"] is expected_full
    assert calls[0][1:] == (resource, expected_full)


@pytest.mark.parametrize(
    ("http_status", "failure"),
    [
        (502, "Spotify HTTP 502"),
        (None, "Spotify connection interrupted"),
    ],
)
def test_live_analysis_job_can_be_cancelled_during_retry_wait(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    http_status: int | None,
    failure: str,
) -> None:
    """Live analysis job can be cancelled during retry wait.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
        http_status: Original http status.
        failure: Original failure.
    """
    from spotify_manager import api

    scenario = LiveAnalysisJobCanBeCancelledDuringRetryWaitScenario(
        http_status=http_status
    )
    monkeypatch.setattr(
        api.library_analysis, "analyse_library_sync_routine", scenario.wait_for_server
    )
    started = client.post("/commands/analyse-library-sync")
    job_id = started.json()["job_id"]
    waiting = wait_for_job_status(client, job_id, {"waiting"})
    assert waiting["retry_at"] is not None
    assert any(
        "Waiting until" in entry["message"] and failure in entry["message"]
        for entry in waiting["logs"]
    )
    cancelled = client.post(f"/commands/library-analysis-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelling"
    result = wait_for_job_status(client, job_id, {"cancelled"})
    assert "Progress was saved" in result["detail"]
    assert any("Cancellation requested" in entry["message"] for entry in result["logs"])


def test_duplicate_active_analysis_is_rejected(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    release = api.Event()

    def blocked_export(**_kwargs):
        release.wait(2)
        return analysis_summary("async")

    monkeypatch.setattr(
        api.library_analysis,
        "analyse_library_async_routine",
        blocked_export,
    )

    first = client.post("/commands/analyse-library-async")
    second = client.post("/commands/analyse-library-async")
    release.set()

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["job_id"] == first.json()["job_id"]
    wait_for_job_status(client, first.json()["job_id"], {"completed"})


def test_active_analysis_jobs_can_be_restored_after_reload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Active analysis jobs can be restored after reload.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
    """
    from spotify_manager import api

    release = api.Event()
    scenario = ActiveAnalysisJobsCanBeRestoredAfterReloadScenario(release=release)
    monkeypatch.setattr(
        api.library_analysis, "analyse_library_async_routine", scenario.blocked_export
    )
    started = client.post("/commands/analyse-library-async").json()
    active = client.get("/commands/library-analysis-jobs")
    assert active.status_code == 200
    assert [job["job_id"] for job in active.json()] == [started["job_id"]]
    assert any(
        entry["message"] == "Still reading exported albums."
        for entry in active.json()[0]["logs"]
    )
    release.set()
    wait_for_job_status(client, started["job_id"], {"completed"})
    assert client.get("/commands/library-analysis-jobs").json() == []


@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_new_year_web_job_routes_and_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, outcome: Exception | None
) -> None:
    """New year web job routes and errors.

    Args:
        client: Original client.
        monkeypatch: Scoped external-boundary substitutions.
        outcome: Original outcome.
    """
    monkeypatch.setattr(
        http_jobs,
        "Settings",
        Mock(
            return_value=SimpleNamespace(
                lastfm_api_key="key", lastfm_username="listener"
            )
        ),
    )
    received = {}
    scenario = NewYearWebJobRoutesAndErrorsScenario(outcome=outcome, received=received)
    monkeypatch.setattr(api.new_year, "run_new_year", scenario.routine)
    started = client.post("/commands/new-year?year=2025")
    assert started.status_code == 202
    identity = started.json()["job_id"]
    deadline = monotonic() + 2
    while monotonic() < deadline:
        job = client.get("/commands/new-year-jobs/" + identity).json()
        if job["status"] == outcome:
            break
        sleep(0.01)
    assert job["status"] == outcome
    assert received["dry_run"] and received["year"] == 2025
    assert job["completed_at"]
    assert client.get("/commands/new-year-jobs").json() == []
    assert (
        client.post("/commands/new-year-jobs/" + identity + "/cancel").status_code
        == 409
    )


def test_new_year_job_conflicts_reconnects_and_cancels(client, monkeypatch):
    monkeypatch.setattr(
        http_jobs, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: None)
    )
    started = client.post("/commands/new-year")
    identity = started.json()["job_id"]
    conflict = client.post("/commands/new-year")
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["command"] == "new_year"
    assert client.get("/commands/new-year-jobs").json()[0]["job_id"] == identity
    cancelled = client.post("/commands/new-year-jobs/" + identity + "/cancel")
    assert cancelled.json()["status"] == "cancelling"
    assert api.get_blast_job(identity).cancel_event.is_set()


@dataclass
class BlastFromThePastEndpointRunsBackgroundJobScenario:
    """Retain the original blast from the past endpoint runs background job fixture.

    Args:
        batch: Original batch observation or resource.
        match: Original match observation or resource.
        received: Original received observation or resource.
        selection: Original selection observation or resource.
    """

    batch: api.blast_from_past.BlastFromPastBatch
    match: api.blast_from_past.SpotifyTrackMatch
    received: dict[str, Any]
    selection: api.blast_from_past.ScrobbleSelection

    def complete(
        self, spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.blast_from_past.BlastFromPastSpotifySummary:
        """Execute the original complete mock boundary.

        Args:
            spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify,
            playlist_id=playlist_id,
            count=kwargs["count"],
            max_playlist_length=kwargs["max_playlist_length"],
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].echo("Searching Spotify track 1/1")
        return api.blast_from_past.BlastFromPastSpotifySummary(
            playlist_id=playlist_id,
            requested_count=10,
            playlist_length_before=4,
            playlist_length_after=4,
            batch=self.batch,
            results=(
                api.blast_from_past.SpotifySelectionResult(
                    selection=self.selection,
                    match=self.match,
                    qualifying_matches=1,
                    action="added",
                ),
            ),
        )

    @classmethod
    def example(cls) -> BlastFromThePastEndpointRunsBackgroundJobScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        received = {}
        scrobble = api.blast_from_past.Scrobble(
            track="Track", artist="Artist", album="Album", timestamp_ms=1
        )
        selection = api.blast_from_past.ScrobbleSelection(
            selected_date=date(2010, 1, 2),
            date_index=1,
            scrobbles_on_date=60,
            page=2,
            total_pages=2,
            direction="bottom up",
            position=3,
            scrobble=scrobble,
        )
        match = api.blast_from_past.SpotifyTrackMatch(
            spotify_id="track-id",
            uri="spotify:track:track-id",
            track="Track - Remastered",
            artists=("Artist",),
            album="Different Album",
            search_rank=2,
            track_similarity=1.0,
            album_similarity=0.2,
            popularity=20,
            liked=True,
        )
        batch = api.blast_from_past.BlastFromPastBatch(
            generated_at=datetime(2026, 7, 22, 13, 0, 52, tzinfo=UTC),
            cutoff_date=date(2021, 12, 31),
            available_dates=3698,
            selections=(selection,),
        )
        return cls(batch=batch, match=match, received=received, selection=selection)

    def _assert_result(self, result: Any) -> None:
        """Verify the original result contract.

        Args:
            result: Original result observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["playlist_id"] == "blast"
        assert self.received["count"] == 10
        assert self.received["max_playlist_length"] is None
        assert self.received["dry_run"] is True
        assert result["dry_run"] is True
        assert result["added"] == 1
        assert result["playlist_length_before"] == 4
        assert result["playlist_length_after"] == 4
        assert result["detail"].startswith("Would add 1")
        assert result["random_org_timestamp"] == "2026-07-22T13:00:52+00:00"
        assert result["selections"][0]["liked"] is True
        assert result["selections"][0]["album_similarity"] == 0.2
        assert any(
            entry["message"] == "Searching Spotify track 1/1"
            for entry in result["logs"]
        )


@dataclass
class BlastFromThePastArtistsEndpointRunsBackgroundJobScenario:
    """Retain the original blast from the past artists endpoint runs background job
    fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def complete(
        self, _spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.blast_from_past_artists.DormantArtistSummary:
        """Execute the original complete mock boundary.

        Args:
            _spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received["playlist_id"] = playlist_id
        self.received["count"] = kwargs["count"]
        self.received["dry_run"] = kwargs["dry_run"]
        kwargs["progress_callback"].progress(0, 5, "Checking dormant artist Artist")
        return api.blast_from_past_artists.DormantArtistSummary(
            current_year=2026,
            history_years=(2022, 2023, 2024, 2025),
            candidate_count=25,
            represented_count=4,
            playlist_length_before=10,
            playlist_length_after=10,
            requested_count=5,
            results=(
                api.blast_from_past_artists.DormantArtistResult(
                    artist="Artist",
                    scrobbles=14,
                    spotify_artist="Artist",
                    track="Liked Track",
                    popularity=78,
                    action="added",
                ),
            ),
        )

    @classmethod
    def example(cls) -> BlastFromThePastArtistsEndpointRunsBackgroundJobScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        received: dict[str, object] = {}
        return cls(received=received)

    def _assert_result(self, result: Any) -> None:
        """Verify the original result contract.

        Args:
            result: Original result observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert result is not None
        assert self.received == {"playlist_id": "blast", "count": 5, "dry_run": True}
        assert result["dry_run"] is True
        assert result["playlist_length_after"] == 10
        assert result["detail"].startswith("Would add 1")
        assert result["added"] == 1
        assert result["candidate_count"] == 25
        assert result["dormant_artist_years"] == [2022, 2023, 2024, 2025]
        assert result["dormant_artist_current_year"] == 2026
        assert result["dormant_artist_represented"] == 4
        assert result["dormant_artist_results"][0]["track"] == "Liked Track"
        assert any(
            log["message"] == "Checking dormant artist Artist" for log in result["logs"]
        )


@dataclass
class DailyMindRadioEndpointRunsBackgroundJobScenario:
    """Retain the original daily mind radio endpoint runs background job fixture.

    Args:
        batch: Original batch observation or resource.
        match: Original match observation or resource.
        selection: Original selection observation or resource.
    """

    batch: api.daily_mind_radio.DailyMindRadioBatch
    match: api.blast_from_past.SpotifyTrackMatch
    selection: api.blast_from_past.ScrobbleSelection

    def complete(
        self, _spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.daily_mind_radio.DailyMindRadioSpotifySummary:
        """Execute the original complete mock boundary.

        Args:
            _spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].echo("Searching Spotify track 1/1")
        assert kwargs["dry_run"] is True
        return api.daily_mind_radio.DailyMindRadioSpotifySummary(
            playlist_id=playlist_id,
            batch=self.batch,
            playlist_length_before=2,
            playlist_length_after=2,
            results=(
                api.blast_from_past.SpotifySelectionResult(
                    selection=self.selection,
                    match=self.match,
                    qualifying_matches=1,
                    action="added",
                ),
            ),
        )


@dataclass
class ActiveDailyMindRadioJobCanBeRestoredScenario:
    """Retain the original active daily mind radio job can be restored fixture.

    Args:
        batch: Original batch observation or resource.
        release: Original release observation or resource.
    """

    batch: api.daily_mind_radio.DailyMindRadioBatch
    release: api.Event

    def blocked(
        self, _spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.daily_mind_radio.DailyMindRadioSpotifySummary:
        """Execute the original blocked mock boundary.

        Args:
            _spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].echo("Reading anniversary dates")
        self.release.wait(2)
        return api.daily_mind_radio.DailyMindRadioSpotifySummary(
            playlist_id=playlist_id,
            batch=self.batch,
            playlist_length_before=None,
            playlist_length_after=None,
            results=(),
        )


@dataclass
class FoundArtEndpointRunsBackgroundJobWithRequestedCountScenario:
    """Retain the original found art endpoint runs background job with requested count
    fixture.

    Args:
        candidate: Original candidate observation or resource.
        match: Original match observation or resource.
        received: Original received observation or resource.
    """

    candidate: api.found_art.FoundArtCandidate
    match: api.blast_from_past.SpotifyTrackMatch
    received: dict[str, Any]

    def complete(
        self, spotify: Any, lastfm: Any, playlist_id: Any, **kwargs: Any
    ) -> api.found_art.FoundArtSummary:
        """Execute the original complete mock boundary.

        Args:
            spotify: Original external mock argument.
            lastfm: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlist_id=playlist_id,
            count=kwargs["count"],
        )
        kwargs["progress_callback"].echo("Getting Last.fm neighbors for seed 1/1")
        return api.found_art.FoundArtSummary(
            generated_at=datetime(2026, 7, 23, 12, 0, tzinfo=UTC),
            week_start=date(2026, 7, 17),
            playlist_id=playlist_id,
            requested_count=kwargs["count"],
            seed_count=1,
            history_tracks=100,
            history_scrobbles=250,
            live_scrobbles_added=3,
            candidate_count=50,
            playlist_length_before=8,
            playlist_length_after=9,
            dry_run=False,
            seeds=(),
            results=(
                api.found_art.FoundArtResult(
                    candidate=self.candidate, match=self.match, action="added"
                ),
            ),
        )


@dataclass
class SauvignonWebJobWaitsForAlbumChoiceAndCompletesScenario:
    """Retain the original sauvignon web job waits for album choice and completes
    fixture.

    Args:
        first_option: Original first option observation or resource.
        received: Original received observation or resource.
        recommendation: Original recommendation observation or resource.
        second_option: Original second option observation or resource.
    """

    first_option: api.sauvignon.SpotifyAlbumOption
    received: dict[str, object]
    recommendation: api.sauvignon.AlbumRecommendation
    second_option: api.sauvignon.SpotifyAlbumOption

    def __call__(
        self,
        spotify: Any,
        lastfm: Any,
        playlist_id: Any,
        choice_reader: Any,
        **kwargs: Any,
    ) -> api.sauvignon.SauvignonSummary:
        """Execute the original complete mock boundary.

        Args:
            spotify: Original external mock argument.
            lastfm: Original external mock argument.
            playlist_id: Original external mock argument.
            choice_reader: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlist_id=playlist_id,
            count=kwargs["count"],
            max_playlist_length=kwargs["max_playlist_length"],
            seed_count=kwargs["seed_count"],
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].echo("Resolving album recommendations")
        choice = choice_reader.choose_album(
            self.recommendation, self.recommendation.options
        )
        self.received["choice"] = choice
        chosen = (
            self.second_option
            if choice == self.second_option.spotify_id
            else self.first_option
        )
        return api.sauvignon.SauvignonSummary(
            generated_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
            week_start=date(2026, 8, 7),
            playlist_id=playlist_id,
            requested_count=1,
            history_albums=400,
            history_scrobbles=12000,
            live_scrobbles_added=4,
            seed_count=30,
            track_candidate_count=100,
            album_candidate_count=25,
            playlist_length_before=19,
            playlist_length_after=19,
            paused=False,
            dry_run=True,
            results=(
                api.sauvignon.SauvignonResult(
                    recommendation=self.recommendation,
                    album=chosen,
                    first_track=api.sauvignon.FirstTrack(
                        "first", "spotify:track:first", "Opening Track"
                    ),
                    action="would add",
                ),
            ),
        )

    @classmethod
    def example(cls) -> SauvignonWebJobWaitsForAlbumChoiceAndCompletesScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        received: dict[str, object] = {}
        first_option = api.sauvignon.SpotifyAlbumOption(
            spotify_id="plain",
            uri="spotify:album:plain",
            artist_id="artist",
            artist="Recommendation Artist",
            album="Recommendation Album",
            release_type="Album",
            release_date="2025-01-01",
            total_tracks=10,
            source_track="Recommended Track",
            source_track_id="track",
            search_rank=1,
            track_similarity=1.0,
            track_popularity=50,
        )
        second_option = api.sauvignon.SpotifyAlbumOption(
            spotify_id="alternate",
            uri="spotify:album:alternate",
            artist_id="artist",
            artist="Recommendation Artist",
            album="Recommendation Album",
            release_type="EP",
            release_date="2025-02-01",
            total_tracks=6,
            source_track="Recommended Track",
            source_track_id="track",
            search_rank=2,
            track_similarity=0.99,
            track_popularity=45,
        )
        recommendation = api.sauvignon.AlbumRecommendation(
            artist="Recommendation Artist",
            album="Recommendation Album",
            key=("recommendation artist", "recommendation album"),
            score=1.4,
            best_match=0.95,
            supporting_tracks=("Recommended Track", "Another Track"),
            options=(first_option, second_option),
            base_rank=3,
            weekly_rank=0.8,
        )
        return cls(
            first_option=first_option,
            received=received,
            recommendation=recommendation,
            second_option=second_option,
        )

    def _assert_waiting(self, client: TestClient, job_id: Any, waiting: Any) -> None:
        """Verify the original waiting contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            waiting: Original waiting observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert waiting["sauvignon_pending_choice"]["album"] == "Recommendation Album"
        assert [
            option["spotify_id"]
            for option in waiting["sauvignon_pending_choice"]["options"]
        ] == ["plain", "alternate"]
        assert [
            job["job_id"]
            for job in client.get("/commands/fill-sauvignon-from-lastfm-jobs").json()
        ] == [job_id]

    def _assert_result(self, client: TestClient, result: Any) -> None:
        """Verify the original result contract.

        Args:
            client: Original client observation.
            result: Original result observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["playlist_id"] == "sauvignon"
        assert self.received["count"] is None
        assert self.received["max_playlist_length"] == 20
        assert self.received["seed_count"] == 30
        assert self.received["dry_run"] is True
        assert self.received["choice"] == "alternate"
        assert result["command"] == "fill_sauvignon_from_lastfm"
        assert result["added"] == 1
        assert result["sauvignon_history_albums"] == 400
        assert result["sauvignon_track_candidate_count"] == 100
        assert result["sauvignon_album_candidate_count"] == 25
        assert result["sauvignon_results"][0]["spotify_album_id"] == "alternate"
        assert result["sauvignon_results"][0]["first_track"] == "Opening Track"
        assert client.get("/commands/fill-sauvignon-from-lastfm-jobs").json() == []


@dataclass
class NewKidsWebJobWaitsForAndAppliesReleaseChoiceScenario:
    """Retain the original new kids web job waits for and applies release choice
    fixture.

    Args:
        composer_playlist: Original composer playlist observation or resource.
        received: Original received observation or resource.
        release: Original release observation or resource.
    """

    composer_playlist: api.composer_playlists.OwnedPlaylist
    received: dict[str, object]
    release: api.new_kids.RankedRelease

    def __call__(
        self,
        spotify: Any,
        new_playlist_id: Any,
        queue_playlist_id: Any,
        great_playlist_id: Any,
        unlucky_playlist_id: Any,
        newfoundland_playlist_id: Any,
        **kwargs: Any,
    ) -> api.new_kids.FlushSummary:
        """Execute the original flush mock boundary.

        Args:
            spotify: Original external mock argument.
            new_playlist_id: Original external mock argument.
            queue_playlist_id: Original external mock argument.
            great_playlist_id: Original external mock argument.
            unlucky_playlist_id: Original external mock argument.
            newfoundland_playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify_type=type(spotify).__name__,
            new_playlist_id=new_playlist_id,
            queue_playlist_id=queue_playlist_id,
            great_playlist_id=great_playlist_id,
            unlucky_playlist_id=unlucky_playlist_id,
            newfoundland_playlist_id=newfoundland_playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].progress(0, 1, "Reviewing Artist")
        choice = kwargs["choice_reader"].choose(
            "Artist", (self.composer_playlist, self.release)
        )
        self.received["choice"] = choice
        kwargs["echo"].echo(f"Selected {choice}")
        return api.new_kids.FlushSummary(
            results=(
                api.new_kids.FlushResult(
                    artist="Artist",
                    source_track="Current Track",
                    source_release="Current Album",
                    current_liked=True,
                    consecutive_unliked=0,
                    action="next release",
                    target_track="Opening Track",
                    target_release="Ranked Album",
                    release_number=2,
                    album_decision="keep",
                    album_liked_tracks=6,
                    album_total_tracks=9,
                    dry_run=kwargs["dry_run"],
                ),
            ),
            prefill=(api.new_kids.FillResult("Queue Artist", "Marker", "moved"),),
            postfill=(),
            playlist_length_before=9,
            playlist_length_after=10,
            paused=False,
            resumed=True,
            dry_run=kwargs["dry_run"],
        )

    @classmethod
    def example(cls) -> NewKidsWebJobWaitsForAndAppliesReleaseChoiceScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        release = api.new_kids.RankedRelease(
            spotify_id="release",
            uri="spotify:album:release",
            name="Ranked Album",
            release_type="Album",
            release_date="2024-01-01",
            total_tracks=9,
            primary_artist_id="artist",
            primary_artist_name="Artist",
            popularity=73,
            top_track_rank=2,
            tier=0,
            identity="ranked album",
            saved=True,
            plain=True,
        )
        composer_playlist = api.composer_playlists.OwnedPlaylist(
            spotify_id="bach-works", name="Complete Bach works", total_tracks=100
        )
        received: dict[str, object] = {}
        return cls(
            composer_playlist=composer_playlist, received=received, release=release
        )

    def _assert_waiting(self, client: TestClient, job_id: Any, waiting: Any) -> None:
        """Verify the original waiting contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            waiting: Original waiting observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert waiting["dry_run"] is True
        assert waiting["new_kids_pending_choice"]["artist"] == "Artist"
        assert waiting["new_kids_pending_choice"]["releases"] == [
            {
                "spotify_id": "bach-works",
                "name": "Complete Bach works",
                "release_type": "Composer works playlist",
                "release_date": "Stored Spotify order",
                "total_tracks": 100,
                "popularity": None,
                "top_track_rank": None,
                "saved": False,
            },
            {
                "spotify_id": "release",
                "name": "Ranked Album",
                "release_type": "Album",
                "release_date": "2024-01-01",
                "total_tracks": 9,
                "popularity": 73,
                "top_track_rank": 2,
                "saved": True,
            },
        ]
        assert [
            job["job_id"] for job in client.get("/commands/flush-new-kids-jobs").json()
        ] == [job_id]

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received == {
            "spotify_type": "FakeSpotify",
            "new_playlist_id": "newkids",
            "queue_playlist_id": "queue2",
            "great_playlist_id": "great",
            "unlucky_playlist_id": "unlucky",
            "newfoundland_playlist_id": "newfoundland",
            "dry_run": True,
            "choice": "release",
        }
        assert completed["processed"] == 1
        assert completed["playlist_length_before"] == 9
        assert completed["playlist_length_after"] == 10
        assert completed["new_kids_resumed"] is True
        assert completed["new_kids_results"][0]["target_track"] == "Opening Track"
        assert completed["new_kids_prefill"][0]["artist"] == "Queue Artist"
        assert any(
            entry["message"] == "Selected release" for entry in completed["logs"]
        )
        assert client.get("/commands/flush-new-kids-jobs").json() == []


@dataclass
class QueueFillWebJobWaitsForArtistMappingScenario:
    """Retain the original queue fill web job waits for artist mapping fixture.

    Args:
        artist: Original artist observation or resource.
        received: Original received observation or resource.
        recommendation: Original recommendation observation or resource.
        track: Original track observation or resource.
    """

    artist: api.release_check.SpotifyArtistCandidate
    received: dict[str, object]
    recommendation: api.the_queue.ArtistRecommendation
    track: api.new_kids.CatalogTrack

    def __call__(
        self,
        spotify: Any,
        lastfm: Any,
        playlists: Any,
        choice_reader: Any,
        **kwargs: Any,
    ) -> api.the_queue.FillSummary:
        """Execute the original fill mock boundary.

        Args:
            spotify: Original external mock argument.
            lastfm: Original external mock argument.
            playlists: Original external mock argument.
            choice_reader: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify_type=type(spotify).__name__,
            lastfm_username=lastfm.username,
            queue=playlists.queue,
            count=kwargs["count"],
            seed_count=kwargs["seed_count"],
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].progress(0, 1, "Resolving Last.fm Artist")
        self.received["choice"] = choice_reader.choose_artist(
            self.recommendation, (self.artist,)
        )
        kwargs["echo"].echo("Would add Spotify Artist - Queue Marker to The Queue.")
        return api.the_queue.FillSummary(
            week_start=date(2026, 8, 7),
            requested_count=2,
            history_artists=100,
            history_scrobbles=500,
            live_scrobbles_added=4,
            seed_count=30,
            candidate_count=200,
            playlist_length_before=8,
            playlist_length_after=8,
            paused=False,
            dry_run=True,
            results=(
                api.the_queue.FillResult(
                    self.recommendation,
                    self.artist,
                    self.track,
                    "would add",
                    followed=True,
                ),
            ),
        )

    @classmethod
    def example(cls) -> QueueFillWebJobWaitsForArtistMappingScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        recommendation = api.the_queue.ArtistRecommendation(
            artist="Last.fm Artist",
            key="lastfmartist",
            score=1.25,
            best_match=0.9,
            supporting_seeds=("Seed One", "Seed Two"),
            base_rank=3,
            weekly_rank=0.8,
        )
        artist = api.release_check.SpotifyArtistCandidate(
            spotify_id="artist-id",
            name="Spotify Artist",
            uri="spotify:artist:artist-id",
            popularity=70,
            followers=500,
            search_rank=1,
            exact_name=False,
        )
        track = api.new_kids.CatalogTrack(
            spotify_id="track-id",
            uri="spotify:track:track-id",
            name="Queue Marker",
            disc_number=1,
            track_number=1,
            primary_artist_id="artist-id",
            primary_artist_name="Spotify Artist",
            popularity=60,
        )
        received: dict[str, object] = {}
        return cls(
            artist=artist, received=received, recommendation=recommendation, track=track
        )

    def _assert_waiting(self, client: TestClient, job_id: Any, waiting: Any) -> None:
        """Verify the original waiting contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            waiting: Original waiting observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert waiting["queue_pending_choice"] == {
            "artist": "Last.fm Artist",
            "base_rank": 3,
            "score": 1.25,
            "supporting_seeds": ["Seed One", "Seed Two"],
            "candidates": [
                {
                    "spotify_id": "artist-id",
                    "name": "Spotify Artist",
                    "popularity": 70,
                    "followers": 500,
                    "exact_name": False,
                }
            ],
        }
        assert [
            job["job_id"]
            for job in client.get("/commands/fill-queue-from-lastfm-jobs").json()
        ] == [job_id]

    def _assert_empty_search(self, empty_search: Any, unavailable: Any) -> None:
        """Verify the original empty search contract.

        Args:
            empty_search: Original empty search observation.
            unavailable: Original unavailable observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert unavailable.status_code == 400
        assert empty_search.status_code == 400

    def _assert_completed(self, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received == {
            "spotify_type": "FakeSpotify",
            "lastfm_username": "lastfm-user",
            "queue": "queue",
            "count": 2,
            "seed_count": 30,
            "dry_run": True,
            "choice": "artist-id",
        }
        assert completed["queue_history_artists"] == 100
        assert completed["queue_seed_count"] == 30
        assert completed["candidate_count"] == 200
        assert completed["queue_fill_results"][0]["track"] == "Queue Marker"
        assert completed["queue_fill_results"][0]["followed"] is True

    def _assert_stale_choice(self, client: TestClient, stale_choice: Any) -> None:
        """Verify the original stale choice contract.

        Args:
            client: Original client observation.
            stale_choice: Original stale choice observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert stale_choice.status_code == 409
        assert client.get("/commands/fill-queue-from-lastfm-jobs").json() == []


@dataclass
class QueueFlushWebJobReturnsLiveDecisionsScenario:
    """Retain the original queue flush web job returns live decisions fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def flush(
        self, spotify: Any, playlists: Any, **kwargs: Any
    ) -> api.the_queue.FlushSummary:
        """Execute the original flush mock boundary.

        Args:
            spotify: Original external mock argument.
            playlists: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify_type=type(spotify).__name__,
            queue=playlists.queue,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].progress(1, 1, "Completed Artist")
        kwargs["echo"].echo("Would promote Artist to Queue 2 with Opening.")
        return api.the_queue.FlushSummary(
            run_id="queue-run",
            playlist_length_before=10,
            playlist_length_after=10,
            total=1,
            processed=1,
            resumed=True,
            dry_run=True,
            results=(
                api.the_queue.FlushResult(
                    artist="Artist",
                    source_track="Current",
                    action="promote",
                    top_tracks=10,
                    top_liked_tracks=5,
                    total_liked_tracks=6,
                    target_track="Opening",
                    target_release="Established Album",
                    reason="six liked tracks",
                    dry_run=True,
                ),
            ),
        )


@dataclass
class Queue2WebJobWaitsForAndAppliesReleaseChoiceScenario:
    """Retain the original queue 2 web job waits for and applies release choice fixture.

    Args:
        received: Original received observation or resource.
        release: Original release observation or resource.
    """

    received: dict[str, object]
    release: api.new_kids.RankedRelease

    def __call__(
        self,
        spotify: Any,
        new_playlist_id: Any,
        queue_playlist_id: Any,
        great_playlist_id: Any,
        unlucky_playlist_id: Any,
        newfoundland_playlist_id: Any,
        **kwargs: Any,
    ) -> api.new_kids.Queue2Summary:
        """Execute the original flush mock boundary.

        Args:
            spotify: Original external mock argument.
            new_playlist_id: Original external mock argument.
            queue_playlist_id: Original external mock argument.
            great_playlist_id: Original external mock argument.
            unlucky_playlist_id: Original external mock argument.
            newfoundland_playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify_type=type(spotify).__name__,
            new_playlist_id=new_playlist_id,
            queue_playlist_id=queue_playlist_id,
            great_playlist_id=great_playlist_id,
            unlucky_playlist_id=unlucky_playlist_id,
            newfoundland_playlist_id=newfoundland_playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].progress(0, 1, "Reviewing Artist")
        choice = kwargs["choice_reader"].choose("Artist", (self.release,))
        self.received["choice"] = choice
        kwargs["echo"].echo(f"Selected {choice}")
        return api.new_kids.Queue2Summary(
            results=(
                api.new_kids.FlushResult(
                    artist="Artist",
                    source_track="Current Track",
                    source_release="Current Album",
                    current_liked=True,
                    consecutive_unliked=0,
                    action="next release",
                    target_track="Opening Track",
                    target_release="Ranked Album",
                    release_number=2,
                    album_decision="keep",
                    album_liked_tracks=6,
                    album_total_tracks=9,
                    dry_run=kwargs["dry_run"],
                ),
            ),
            prefill=(api.new_kids.FillResult("First Artist", "Marker", "moved"),),
            queue_length_before=20,
            queue_length_after=19,
            new_kids_length_before=9,
            new_kids_length_after=10,
            paused=False,
            resumed=True,
            dry_run=kwargs["dry_run"],
        )


@dataclass
class Queue3WebJobHandlesReleaseAndComposerChoicesScenario:
    """Retain the original queue 3 web job handles release and composer choices fixture.

    Args:
        received: Original received observation or resource.
        source: Original source observation or resource.
    """

    received: dict[str, object]
    source: api.new_wine.PlaylistTrack

    def boundary_release(
        self, spotify_id: str, name: str, date: str
    ) -> api.slow_listening.DiscographyRelease:
        """Execute the original boundary release mock boundary.

        Args:
            spotify_id: Original external mock argument.
            name: Original external mock argument.
            date: Original external mock argument.

        Returns:
            Original fixture result.
        """
        return api.slow_listening.DiscographyRelease(
            spotify_id=spotify_id,
            uri=f"spotify:album:{spotify_id}",
            name=name,
            release_type="Album",
            release_date=date,
            chronology_date=date,
            total_tracks=2,
            primary_artist_id="artist",
            primary_artist_name="Artist",
            identity=name.casefold(),
            saved=False,
            plain=True,
            edition_rank=0,
        )

    def __call__(
        self, spotify: Any, playlist_id: Any, transition_reader: Any, **kwargs: Any
    ) -> api.queue_3.FlushSummary:
        """Execute the original flush mock boundary.

        Args:
            spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            transition_reader: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify_type=type(spotify).__name__,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].progress(0, 2, "Reviewing Artist")
        self.received["release_choice"] = transition_reader.choose_transition(
            self.source,
            self.boundary_release("current", "Current Release", "2020-01-01"),
            self.boundary_release("next", "Next Release", "2021-01-01"),
        )
        self.received["composer_choice"] = kwargs[
            "composer_playlist_reader"
        ].choose_composer(
            "Johann Sebastian Bach",
            (
                api.queue_3.OwnedPlaylist("bach-a", "Bach works", 120),
                api.queue_3.OwnedPlaylist("bach-b", "All of Bach", 3197),
            ),
        )
        kwargs["progress_callback"].progress(2, 2, "Completed Queue 3")
        kwargs["echo"].echo("Queue 3 choices applied")
        return api.queue_3.FlushSummary(
            run_id="queue-3-run",
            total=2,
            processed=2,
            advanced=1,
            changed_releases=1,
            completed_artists=0,
            skipped=0,
            annual_import=(
                api.queue_3.AnnualImportResult(
                    artist="Imported Artist",
                    track="Marker",
                    source_year=2025,
                    action="would add",
                ),
            ),
            paused=False,
            dry_run=kwargs["dry_run"],
            resumed=True,
            results=(
                api.queue_3.FlushResult(
                    artist="Artist",
                    source_track="Current Track",
                    source_release="Current Release",
                    action="next release",
                    target_track="Opening Track",
                    target_release="Next Release",
                    album_decision="keep",
                    album_liked_tracks=1,
                    album_total_tracks=2,
                    dry_run=kwargs["dry_run"],
                ),
                api.queue_3.FlushResult(
                    artist="Johann Sebastian Bach",
                    source_track="BWV 1",
                    source_release="Recording",
                    action="composer playlist",
                    target_track="BWV 2",
                    target_release="Another Recording",
                    composer_playlist="All of Bach",
                    dry_run=kwargs["dry_run"],
                ),
            ),
        )

    @classmethod
    def example(cls) -> Queue3WebJobHandlesReleaseAndComposerChoicesScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        source_release = api.new_wine.ReleaseCandidate(
            spotify_id="current",
            uri="spotify:album:current",
            name="Current Release",
            release_type="Album",
            release_date="2020-01-01",
            total_tracks=2,
            primary_artist_id="artist",
            primary_artist_name="Artist",
        )
        source = api.new_wine.PlaylistTrack(
            spotify_id="current-track",
            uri="spotify:track:current-track",
            name="Current Track",
            primary_artist_id="artist",
            primary_artist_name="Artist",
            release=source_release,
        )
        received: dict[str, object] = {}
        return cls(received=received, source=source)

    def _assert_release_wait(
        self, client: TestClient, job_id: Any, release_wait: Any
    ) -> None:
        """Verify the original release wait contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            release_wait: Original release wait observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert (
            release_wait["queue_3_pending_choice"]["next_release"]["name"]
            == "Next Release"
        )
        assert [
            job["job_id"] for job in client.get("/commands/flush-queue-3-jobs").json()
        ] == [job_id]

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received == {
            "spotify_type": "FakeSpotify",
            "playlist_id": "queue3",
            "dry_run": True,
            "release_choice": "advance",
            "composer_choice": "bach-b",
        }
        assert completed["run_id"] == "queue-3-run"
        assert completed["queue_3_resumed"] is True
        assert completed["queue_3_changed_releases"] == 1
        assert completed["queue_3_results"][1]["composer_playlist"] == "All of Bach"
        assert completed["queue_3_annual_import"][0]["artist"] == "Imported Artist"
        assert any(
            entry["message"] == "Queue 3 choices applied" for entry in completed["logs"]
        )
        assert client.get("/commands/flush-queue-3-jobs").json() == []


@dataclass
class Queue3PreviousYearImportHasASeparateWebActionScenario:
    """Retain the original queue 3 previous year import has a separate web action
    fixture.

    Args:
        received: Original received observation or resource.
    """

    received: dict[str, object]

    def import_previous_year(
        self, spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.queue_3.AnnualImportSummary:
        """Execute the original import previous year mock boundary.

        Args:
            spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify_type=type(spotify).__name__,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].progress(1, 1, "Checked Great Discoveries 2025")
        kwargs["echo"].echo("Annual import checked")
        return api.queue_3.AnnualImportSummary(
            active_year=2026,
            source_year=2025,
            additions=1,
            already_present=2,
            already_completed=False,
            dry_run=kwargs["dry_run"],
            results=(
                api.queue_3.AnnualImportResult(
                    artist="Imported Artist",
                    track="Marker",
                    source_year=2025,
                    action="would add",
                ),
            ),
        )


@dataclass
class NewWineWebJobWaitsForAndAppliesReleaseChoiceScenario:
    """Retain the original new wine web job waits for and applies release choice
    fixture.

    Args:
        alternative: Original alternative observation or resource.
        current: Original current observation or resource.
        received: Original received observation or resource.
        source: Original source observation or resource.
    """

    alternative: api.new_wine.ReleaseCandidate
    current: api.new_wine.ReleaseCandidate
    received: dict[str, object]
    source: api.new_wine.PlaylistTrack

    def __call__(
        self,
        spotify: Any,
        new_playlist_id: Any,
        sauvignon_playlist_id: Any,
        **kwargs: Any,
    ) -> api.new_wine.FlushSummary:
        """Execute the original flush mock boundary.

        Args:
            spotify: Original external mock argument.
            new_playlist_id: Original external mock argument.
            sauvignon_playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify,
            new_playlist_id=new_playlist_id,
            sauvignon_playlist_id=sauvignon_playlist_id,
            wine_cellar_playlist_id=kwargs["wine_cellar_playlist_id"],
            dry_run=kwargs["dry_run"],
            no_discovery=kwargs["no_discovery"],
        )
        kwargs["progress_callback"].progress(0, 1, "Reviewing Current Track")
        choice = kwargs["choice_reader"].choose_release(
            self.source, (self.current, self.alternative)
        )
        self.received["choice"] = choice
        kwargs["echo"].echo(f"Selected {choice}")
        return api.new_wine.FlushSummary(
            run_id="run",
            total=1,
            processed=1,
            advanced=1,
            dropped=0,
            sent_to_sauvignon=0,
            completed_singles=0,
            skipped=0,
            albums_unsaved=0,
            paused=False,
            dry_run=kwargs["dry_run"],
            resumed=False,
            results=(
                api.new_wine.FlushResult(
                    source_track=self.source.name,
                    artist=self.source.primary_artist_name,
                    release=self.alternative.name,
                    release_type=self.alternative.release_type,
                    current_liked=False,
                    consecutive_unliked=1,
                    action="advance",
                    target_track="Opening Track",
                    advance_reason="next_liked_track",
                    dry_run=kwargs["dry_run"],
                ),
            ),
            refill=api.new_wine.CellarRefillSummary(
                target_size=10,
                before=8,
                after=10,
                added=2,
                removed_from_cellar=2,
                ineligible=1,
                no_discovery=kwargs["no_discovery"],
                results=(
                    api.new_wine.CellarRefillResult(
                        source_track="Not Eligible",
                        artist="Discovery Artist",
                        action="ineligible",
                        liked_tracks=2,
                        saved_albums=0,
                        dry_run=kwargs["dry_run"],
                    ),
                    api.new_wine.CellarRefillResult(
                        source_track="Cellar Track",
                        artist="Known Artist",
                        action="moved",
                        liked_tracks=18,
                        saved_albums=1,
                        dry_run=kwargs["dry_run"],
                    ),
                ),
            ),
        )

    @classmethod
    def example(cls) -> NewWineWebJobWaitsForAndAppliesReleaseChoiceScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        current = api.new_wine.ReleaseCandidate(
            spotify_id="current",
            uri="spotify:album:current",
            name="Current Single",
            release_type="Single",
            release_date="2026-01-01",
            total_tracks=1,
            primary_artist_id="artist",
            primary_artist_name="Artist",
        )
        alternative = api.new_wine.ReleaseCandidate(
            spotify_id="alternative",
            uri="spotify:album:alternative",
            name="New Album",
            release_type="Album",
            release_date="2026-02-01",
            total_tracks=8,
            primary_artist_id="artist",
            primary_artist_name="Artist",
        )
        source = api.new_wine.PlaylistTrack(
            spotify_id="track",
            uri="spotify:track:track",
            name="Current Track",
            primary_artist_id="artist",
            primary_artist_name="Artist",
            release=current,
        )
        received: dict[str, object] = {}
        return cls(
            alternative=alternative, current=current, received=received, source=source
        )

    def _assert_waiting(self, client: TestClient, job_id: Any, waiting: Any) -> None:
        """Verify the original waiting contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            waiting: Original waiting observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert waiting["dry_run"] is True
        assert waiting["no_discovery"] is True
        assert waiting["pending_choice"]["source_track"] == "Current Track"
        assert waiting["pending_choice"]["terminal_release"] is False
        assert [
            release["spotify_id"] for release in waiting["pending_choice"]["releases"]
        ] == ["current", "alternative"]
        assert [
            job["job_id"] for job in client.get("/commands/flush-new-wine-jobs").json()
        ] == [job_id]

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["new_playlist_id"] == "new"
        assert self.received["sauvignon_playlist_id"] == "sauv"
        assert self.received["wine_cellar_playlist_id"] == "cellar"
        assert self.received["dry_run"] is True
        assert self.received["no_discovery"] is True
        assert self.received["choice"] == "alternative"
        assert completed["processed"] == 1
        assert completed["advanced"] == 1
        assert completed["new_wine_results"][0]["target_track"] == "Opening Track"
        assert completed["new_wine_results"][0]["advance_reason"] == "next_liked_track"
        assert completed["new_wine_results"][0]["continuation_release"] is None
        assert completed["new_wine_results"][0]["continuation_track"] is None
        assert completed["new_wine_refill"] == {
            "target_size": 10,
            "before": 8,
            "after": 10,
            "added": 2,
            "removed_from_cellar": 2,
            "ineligible": 1,
            "no_discovery": True,
            "results": [
                {
                    "artist": "Known Artist",
                    "source_track": "Cellar Track",
                    "action": "moved",
                    "liked_tracks": 18,
                    "saved_albums": 1,
                }
            ],
        }
        assert any(
            entry["message"] == "Selected alternative" for entry in completed["logs"]
        )
        assert client.get("/commands/flush-new-wine-jobs").json() == []


@dataclass
class NewWineWebJobAcceptsCanonicalAlbumEndpointScenario:
    """Retain the original new wine web job accepts canonical album endpoint fixture.

    Args:
        received: Original received observation or resource.
        source: Original source observation or resource.
        tracks: Original tracks observation or resource.
    """

    received: dict[str, object]
    source: api.new_wine.PlaylistTrack
    tracks: tuple[object, ...]

    def __call__(
        self, _spotify: Any, _new_playlist: Any, _sauvignon_playlist: Any, **kwargs: Any
    ) -> api.new_wine.FlushSummary:
        """Execute the original flush mock boundary.

        Args:
            _spotify: Original external mock argument.
            _new_playlist: Original external mock argument.
            _sauvignon_playlist: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received["enabled"] = kwargs["choose_album_endpoints"]
        self.received["choice"] = kwargs["endpoint_choice_reader"].choose_endpoint(
            self.source, self.tracks, 4
        )
        return api.new_wine.FlushSummary(
            run_id="run",
            total=1,
            processed=1,
            advanced=0,
            dropped=0,
            sent_to_sauvignon=1,
            completed_singles=0,
            skipped=0,
            albums_unsaved=0,
            paused=False,
            dry_run=kwargs["dry_run"],
            resumed=False,
            results=(
                api.new_wine.FlushResult(
                    source_track=self.source.name,
                    artist=self.source.primary_artist_name,
                    release=self.source.release.name,
                    release_type=self.source.release.release_type,
                    current_liked=True,
                    consecutive_unliked=0,
                    action="sauvignon",
                    target_track="Track 1",
                    canonical_track_count=5,
                    canonical_cutoff_track=self.source.name,
                    dry_run=kwargs["dry_run"],
                ),
            ),
        )


@dataclass
class SlowListeningWebJobHandlesAllInteractiveChoicesScenario:
    """Retain the original slow listening web job handles all interactive choices
    fixture.

    Args:
        first_release: Original first release observation or resource.
        received: Original received observation or resource.
        second_release: Original second release observation or resource.
        source: Original source observation or resource.
        source_release: Original source release observation or resource.
        target: Original target observation or resource.
    """

    first_release: api.slow_listening.DiscographyRelease
    received: dict[str, object]
    second_release: api.slow_listening.DiscographyRelease
    source: api.new_wine.PlaylistTrack
    source_release: api.new_wine.ReleaseCandidate
    target: api.new_wine.ReleaseTrack

    def flush(
        self, spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.slow_listening.FlushSummary:
        """Execute the original flush mock boundary.

        Args:
            spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify, playlist_id=playlist_id, dry_run=kwargs["dry_run"]
        )
        kwargs["progress_callback"].progress(0, 1, "Reviewing Source Track")
        self.received["track_choice"] = kwargs["action_reader"].choose_track(
            self.source, self.target, self.first_release
        )
        self.received["release_order"] = kwargs["order_reader"].order_releases(
            "2021-01-01", (self.first_release, self.second_release)
        )
        kwargs["completion_notifier"].complete(self.source)
        kwargs["echo"].echo("Slow Listening choices applied")
        return api.slow_listening.FlushSummary(
            run_id="run",
            total=1,
            processed=1,
            advanced=1,
            completed_artists=0,
            skipped=0,
            paused=False,
            dry_run=kwargs["dry_run"],
            resumed=False,
            results=(
                api.slow_listening.FlushResult(
                    source_track=self.source.name,
                    source_release=self.source_release.name,
                    artist=self.source.primary_artist_name,
                    action="advance",
                    target_track=self.target.name,
                    target_release=self.first_release.name,
                    skipped_candidates=("Skipped Track (Source Album)",),
                    dry_run=kwargs["dry_run"],
                ),
            ),
        )

    @classmethod
    def example(cls) -> SlowListeningWebJobHandlesAllInteractiveChoicesScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        source_release = api.new_wine.ReleaseCandidate(
            spotify_id="source-release",
            uri="spotify:album:source-release",
            name="Source Album",
            release_type="Album",
            release_date="2020-01-01",
            total_tracks=2,
            primary_artist_id="artist",
            primary_artist_name="Artist",
        )
        source = api.new_wine.PlaylistTrack(
            spotify_id="source-track",
            uri="spotify:track:source-track",
            name="Source Track",
            primary_artist_id="artist",
            primary_artist_name="Artist",
            release=source_release,
        )
        target = api.new_wine.ReleaseTrack(
            spotify_id="target-track",
            uri="spotify:track:target-track",
            name="Target Track",
            disc_number=1,
            track_number=1,
        )
        first_release = api.slow_listening.DiscographyRelease(
            spotify_id="first-release",
            uri="spotify:album:first-release",
            name="First Release",
            release_type="Album",
            release_date="2021-01-01",
            chronology_date="2021-01-01",
            total_tracks=8,
            primary_artist_id="artist",
            primary_artist_name="Artist",
            identity="first release",
            saved=True,
            plain=True,
            edition_rank=0,
        )
        second_release = api.slow_listening.DiscographyRelease(
            spotify_id="second-release",
            uri="spotify:album:second-release",
            name="Second Release",
            release_type="EP",
            release_date="2021-01-01",
            chronology_date="2021-01-01",
            total_tracks=4,
            primary_artist_id="artist",
            primary_artist_name="Artist",
            identity="second release",
            saved=False,
            plain=True,
            edition_rank=0,
        )
        received: dict[str, object] = {}
        return cls(
            first_release=first_release,
            received=received,
            second_release=second_release,
            source=source,
            source_release=source_release,
            target=target,
        )

    def _assert_track_waiting(
        self, client: TestClient, job_id: Any, track_waiting: Any
    ) -> None:
        """Verify the original track waiting contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            track_waiting: Original track waiting observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert track_waiting["slow_listening_pending_choice"] == {
            "kind": "track",
            "artist": "Artist",
            "source_track": "Source Track",
            "source_release": "Source Album",
            "target_track": "Target Track",
            "target_release": "First Release",
            "release_date": None,
            "releases": [],
        }
        assert [
            job["job_id"]
            for job in client.get("/commands/flush-slow-listening-jobs").json()
        ] == [job_id]

    def _assert_pending_order(self, pending_order: Any) -> None:
        """Verify the original pending order contract.

        Args:
            pending_order: Original pending order observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert pending_order["kind"] == "release_order"
        assert [release["spotify_id"] for release in pending_order["releases"]] == [
            "first-release",
            "second-release",
        ]

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["playlist_id"] == "slow"
        assert self.received["dry_run"] is False
        assert self.received["track_choice"] == "advance"
        assert self.received["release_order"] == ("second-release", "first-release")
        assert completed["processed"] == 1
        assert completed["advanced"] == 1
        assert completed["slow_listening_results"][0]["target_track"] == "Target Track"
        assert completed["slow_listening_results"][0]["skipped_candidates"] == [
            "Skipped Track (Source Album)"
        ]
        assert any(
            entry["message"] == "Slow Listening choices applied"
            for entry in completed["logs"]
        )
        assert client.get("/commands/flush-slow-listening-jobs").json() == []


@dataclass
class SlowListeningWebJobRetriesAConnectionResetScenario:
    """Retain the original slow listening web job retries a connection reset fixture.

    Args:
        attempts: Original attempts observation or resource.
    """

    attempts: int

    def flush(
        self, _spotify: Any, _playlist_id: Any, **kwargs: Any
    ) -> api.slow_listening.FlushSummary:
        """Execute the original flush mock boundary.

        Args:
            _spotify: Original external mock argument.
            _playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        for attempt in kwargs["retry_call"].attempts(
            "loading the Slow Listening playlist"
        ):
            with attempt:
                self.load_playlist()
        return api.slow_listening.FlushSummary(
            run_id="run",
            total=0,
            processed=0,
            advanced=0,
            completed_artists=0,
            skipped=0,
            paused=False,
            dry_run=kwargs["dry_run"],
            resumed=False,
            results=(),
        )

    def load_playlist(self) -> None:
        """Execute the original load playlist mock boundary."""
        self.attempts += 1
        if self.attempts == 1:
            raise RequestsConnectionError(
                "Connection aborted.",
                ConnectionResetError(104, "Connection reset by peer"),
            )


@dataclass
class SomethingOldWebJobHandlesAllInteractiveChoicesScenario:
    """Retain the original something old web job handles all interactive choices
    fixture.

    Args:
        artist: Original artist observation or resource.
        first_spotify_artist: Original first spotify artist observation or resource.
        history_summary: Original history summary observation or resource.
        received: Original received observation or resource.
        release: Original release observation or resource.
        second_spotify_artist: Original second spotify artist observation or resource.
        selected_track: Original selected track observation or resource.
    """

    artist: api.something_old.GoldenOldieArtist
    first_spotify_artist: api.something_old.SpotifyArtistCandidate
    history_summary: api.scrobble_history.ScrobbleHistorySummary
    received: dict[str, object]
    release: api.slow_listening.DiscographyRelease
    second_spotify_artist: api.something_old.SpotifyArtistCandidate
    selected_track: api.something_old.SelectedTrack

    def __call__(
        self, spotify: Any, lastfm: Any, playlist_id: Any, **kwargs: Any
    ) -> api.something_old.SomethingOldSummary:
        """Execute the original run mock boundary.

        Args:
            spotify: Original external mock argument.
            lastfm: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].echo("Calculating Golden Oldies")
        self.received["artist_choice"] = kwargs["artist_choice_reader"].choose_artist(
            self.artist, (self.first_spotify_artist, self.second_spotify_artist)
        )
        self.received["mode_choice"] = kwargs["mode_reader"].choose_mode(
            self.artist, self.first_spotify_artist
        )
        self.received["album_choice"] = kwargs["album_choice_reader"].choose_album(
            self.artist, (self.release,)
        )
        return api.something_old.SomethingOldSummary(
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            playlist_id=playlist_id,
            playlist_length_before=0,
            playlist_length_after=0,
            dry_run=True,
            action="would add",
            history_refresh=self.history_summary,
            ranking_preview=(self.artist,),
            artist=self.artist,
            spotify_artist=self.first_spotify_artist,
            mode="album",
            release=self.release,
            tracks=(self.selected_track,),
        )

    @classmethod
    def example(cls) -> SomethingOldWebJobHandlesAllInteractiveChoicesScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        artist = api.something_old.GoldenOldieArtist(
            artist="Old Artist",
            scrobbles=50,
            average_scrobble_ms=1000,
            first_scrobble_ms=1,
            last_scrobble_ms=2000,
            top_tracks=(),
        )
        first_spotify_artist = api.something_old.SpotifyArtistCandidate(
            spotify_id="artist-one",
            name="Old Artist",
            uri="spotify:artist:artist-one",
            popularity=60,
            followers=10000,
            search_rank=1,
        )
        second_spotify_artist = api.something_old.SpotifyArtistCandidate(
            spotify_id="artist-two",
            name="Old Artist",
            uri="spotify:artist:artist-two",
            popularity=10,
            followers=20,
            search_rank=2,
        )
        release = api.slow_listening.DiscographyRelease(
            spotify_id="release-id",
            uri="spotify:album:release-id",
            name="Old Album",
            release_type="Album",
            release_date="2000-01-01",
            chronology_date="2000-01-01",
            total_tracks=2,
            primary_artist_id="artist-one",
            primary_artist_name="Old Artist",
            identity="old album",
            saved=True,
            plain=True,
            edition_rank=0,
        )
        selected_track = api.something_old.SelectedTrack(
            spotify_id="track-id",
            uri="spotify:track:track-id",
            track="Old Track",
            album="Old Album",
            artists=("Old Artist",),
            source="Album: Old Album",
        )
        history = tuple(
            api.blast_from_past.Scrobble(
                track="Old Track",
                artist="Old Artist",
                album="Old Album",
                timestamp_ms=index + 1,
            )
            for index in range(50)
        )
        history_summary = api.scrobble_history.ScrobbleHistorySummary(
            checked_at=datetime(2026, 8, 4, tzinfo=UTC),
            username="man-et-arms",
            history=history,
            export_scrobbles=49,
            legacy_scrobbles_added=0,
            live_scrobbles_added=1,
            dry_run=True,
            persisted=False,
            backup_path=None,
        )
        received: dict[str, object] = {}
        return cls(
            artist=artist,
            first_spotify_artist=first_spotify_artist,
            history_summary=history_summary,
            received=received,
            release=release,
            second_spotify_artist=second_spotify_artist,
            selected_track=selected_track,
        )

    def _assert_artist_waiting(
        self, artist_waiting: Any, client: TestClient, job_id: Any
    ) -> None:
        """Verify the original artist waiting contract.

        Args:
            artist_waiting: Original artist waiting observation.
            client: Original client observation.
            job_id: Original job id observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert artist_waiting["something_old_pending_choice"]["kind"] == "artist"
        assert [
            candidate["spotify_id"]
            for candidate in artist_waiting["something_old_pending_choice"][
                "artist_candidates"
            ]
        ] == ["artist-one", "artist-two"]
        assert [
            job["job_id"] for job in client.get("/commands/something-old-jobs").json()
        ] == [job_id]

    def _assert_mode_waiting(self, mode_waiting: Any) -> None:
        """Verify the original mode waiting contract.

        Args:
            mode_waiting: Original mode waiting observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert mode_waiting["something_old_pending_choice"]["kind"] == "mode"
        assert mode_waiting["something_old_pending_choice"]["scrobbles"] == 50

    def _assert_pending_album(self, pending_album: Any) -> None:
        """Verify the original pending album contract.

        Args:
            pending_album: Original pending album observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert pending_album["kind"] == "album"
        assert pending_album["releases"][0]["spotify_id"] == "release-id"

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["playlist_id"] == "0000000000000000000000"
        assert self.received["dry_run"] is True
        assert self.received["artist_choice"] == "artist-one"
        assert self.received["mode_choice"] == "album"
        assert self.received["album_choice"] == "release-id"
        assert completed["something_old_action"] == "would add"
        assert completed["something_old_artist"] == "Old Artist"
        assert completed["something_old_release"] == "Old Album"
        assert completed["something_old_tracks"][0]["track"] == "Old Track"
        assert completed["history_scrobbles"] == 50
        assert completed["live_scrobbles_added"] == 1
        assert any(
            entry["message"] == "Calculating Golden Oldies"
            for entry in completed["logs"]
        )
        assert client.get("/commands/something-old-jobs").json() == []


@dataclass
class ReleaseCheckWebJobHandlesSearchMappingAndReleaseChoiceScenario:
    """Retain the original release check web job handles search mapping and release
    choice fixture.

    Args:
        artist: Original artist observation or resource.
        first_candidate: Original first candidate observation or resource.
        received: Original received observation or resource.
        release: Original release observation or resource.
        result: Original result observation or resource.
        selected_candidate: Original selected candidate observation or resource.
        track: Original track observation or resource.
    """

    artist: api.release_check.RankedArtist
    first_candidate: api.release_check.SpotifyArtistCandidate
    received: dict[str, object]
    release: api.release_check.ReleaseCandidate
    result: api.release_check.ReleaseCheckResult
    selected_candidate: api.release_check.SpotifyArtistCandidate
    track: api.release_check.ReleaseTrack

    def __call__(
        self, spotify: Any, lastfm: Any, playlists: Any, **kwargs: Any
    ) -> api.release_check.ReleaseCheckSummary:
        """Execute the original run mock boundary.

        Args:
            spotify: Original external mock argument.
            lastfm: Original external mock argument.
            playlists: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlists=playlists,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"].progress(0, 1, "Resolving release-check artist")
        self.received["search_choice"] = kwargs["artist_choice_reader"].choose_artist(
            self.artist, (self.first_candidate,)
        )
        self.received["artist_choice"] = kwargs["artist_choice_reader"].choose_artist(
            self.artist, (self.selected_candidate,)
        )
        self.received["release_choice"] = kwargs[
            "release_choice_reader"
        ].choose_release(
            self.artist, self.release, self.track, ("Wine Cellar", "New Vintage"), False
        )
        return api.release_check.ReleaseCheckSummary(
            run_id="release-check-run",
            checked_from=date(2026, 8, 1),
            checked_through=date(2026, 8, 7),
            artists_total=1,
            artists_processed=1,
            dry_run=True,
            resumed=True,
            paused=False,
            wine_cellar_duplicates_removed=2,
            history_refresh=None,
            results=(self.result,),
        )

    @classmethod
    def example(cls) -> ReleaseCheckWebJobHandlesSearchMappingAndReleaseChoiceScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        artist = api.release_check.RankedArtist(
            key="lastfm artist", name="Last.fm Artist", scrobbles=250, rank=12
        )
        first_candidate = api.release_check.SpotifyArtistCandidate(
            spotify_id="artist-one",
            name="Different Artist",
            uri="spotify:artist:artist-one",
            popularity=20,
            followers=100,
            search_rank=1,
            exact_name=False,
        )
        selected_candidate = api.release_check.SpotifyArtistCandidate(
            spotify_id="artist-two",
            name="Last.fm Artist",
            uri="spotify:artist:artist-two",
            popularity=70,
            followers=10000,
            search_rank=1,
            exact_name=True,
        )
        release = api.release_check.ReleaseCandidate(
            spotify_id="release-id",
            uri="spotify:album:release-id",
            name="New Album Deluxe",
            release_type="Album",
            release_date="2026-08-01",
            release_date_precision="day",
            total_tracks=10,
            primary_artist_id="artist-two",
            primary_artist_name="Last.fm Artist",
        )
        track = api.release_check.ReleaseTrack(
            spotify_id="track-id",
            uri="spotify:track:track-id",
            name="Opening Track",
            primary_artist_id="artist-two",
            primary_artist_name="Last.fm Artist",
            disc_number=1,
            track_number=1,
        )
        result = api.release_check.ReleaseCheckResult(
            artist=artist.name,
            artist_rank=artist.rank,
            artist_scrobbles=artist.scrobbles,
            spotify_artist_id=selected_candidate.spotify_id,
            release_id=release.spotify_id,
            release=release.name,
            release_type=release.release_type,
            release_date=release.release_date,
            first_track_id=track.spotify_id,
            first_track=track.name,
            linked_future_release=None,
            wine_cellar_action="would add",
            new_vintage_action="would add",
            reason=None,
            dry_run=True,
        )
        received: dict[str, object] = {}
        return cls(
            artist=artist,
            first_candidate=first_candidate,
            received=received,
            release=release,
            result=result,
            selected_candidate=selected_candidate,
            track=track,
        )

    def _assert_first_mapping(
        self, client: TestClient, first_mapping: Any, job_id: Any
    ) -> None:
        """Verify the original first mapping contract.

        Args:
            client: Original client observation.
            first_mapping: Original first mapping observation.
            job_id: Original job id observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert first_mapping["release_check_pending_choice"]["kind"] == "artist"
        assert first_mapping["release_check_pending_choice"]["artist_rank"] == 12
        assert (
            client.post(
                f"/commands/check-new-releases-jobs/{job_id}/choice",
                json={"choice": "search:"},
            ).status_code
            == 400
        )

    def _assert_second_mapping(
        self, client: TestClient, job_id: Any, second_mapping: Any
    ) -> None:
        """Verify the original second mapping contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            second_mapping: Original second mapping observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert (
            second_mapping["release_check_pending_choice"]["artist_candidates"][0][
                "spotify_id"
            ]
            == "artist-two"
        )
        assert (
            client.post(
                f"/commands/check-new-releases-jobs/{job_id}/choice",
                json={"choice": "artist-two"},
            ).status_code
            == 200
        )

    def _assert_pending(self, client: TestClient, job_id: Any, pending: Any) -> None:
        """Verify the original pending contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            pending: Original pending observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert pending["kind"] == "release"
        assert pending["tags"] == ["DELUXE"]
        assert pending["destinations"] == ["Wine Cellar", "New Vintage"]
        assert pending["unattached_single"] is False
        assert (
            client.post(
                f"/commands/check-new-releases-jobs/{job_id}/choice",
                json={"choice": "add"},
            ).status_code
            == 200
        )

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["search_choice"] == "search:Lastfm Artist Band"
        assert self.received["artist_choice"] == "artist-two"
        assert self.received["release_choice"] == "add"
        assert self.received["dry_run"] is True
        assert completed["release_check_checked_through"] == "2026-08-07"
        assert completed["release_check_resumed"] is True
        assert completed["release_check_results"][0]["release"] == "New Album Deluxe"
        assert client.get("/commands/check-new-releases-jobs").json() == []


@dataclass
class DiscographyWebJobCollectsReleasesAndConfirmsRemovalScenario:
    """Retain the original discography web job collects releases and confirms removal
    fixture.

    Args:
        artist: Original artist observation or resource.
        artist_candidates: Original artist candidates observation or resource.
        live: Original live observation or resource.
        received: Original received observation or resource.
        studio: Original studio observation or resource.
    """

    artist: api.discography.QueueArtist
    artist_candidates: tuple[api.something_old.SpotifyArtistCandidate, ...]
    live: api.discography.CatalogRelease
    received: dict[str, object]
    studio: api.discography.CatalogRelease

    def build(
        self, _spotify: Any, playlist_ids: Any, release_selector: Any, **kwargs: Any
    ) -> api.discography.DiscographyPlan:
        """Execute the original build mock boundary.

        Args:
            _spotify: Original external mock argument.
            playlist_ids: Original external mock argument.
            release_selector: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received["playlist_ids"] = playlist_ids
        self.received["queue_3_playlist_id"] = kwargs["queue_3_playlist_id"]
        kwargs["progress_callback"].echo("Loading next discography artist")
        self.received["mapped_artist_id"] = kwargs[
            "historical_artist_choice_reader"
        ].choose_artist("Artist", self.artist_candidates)
        selected_ids = release_selector.select_releases(
            self.artist, (self.studio, self.live)
        )
        self.received["selected_ids"] = selected_ids
        selected = tuple(
            release
            for release in (self.studio, self.live)
            if release.spotify_id in selected_ids
        )
        selection = api.discography.ArtistSelection(
            spotify_id=self.artist.spotify_id,
            name=self.artist.name,
            source_queue=self.artist.queue,
            releases=selected,
            markers=(),
        )
        return api.discography.DiscographyPlan(
            start_queue="requeue",
            next_queue="memory_lane",
            artists=(selection,),
            total_releases=len(selected),
            open_slots=-len(selected) % 10,
        )

    def apply(
        self, _spotify: Any, plan: Any, **kwargs: Any
    ) -> api.discography.DiscographyRunSummary:
        """Execute the original apply mock boundary.

        Args:
            _spotify: Original external mock argument.
            plan: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received["applied_plan"] = plan
        kwargs["progress_callback"].echo("Removing confirmed artists")
        return api.discography.DiscographyRunSummary(
            removed_artists=1, removed_markers=2, next_queue="memory_lane"
        )

    @classmethod
    def example(cls) -> DiscographyWebJobCollectsReleasesAndConfirmsRemovalScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        received: dict[str, object] = {}
        artist = api.discography.QueueArtist("artist", "Artist", "requeue")
        studio = api.discography.CatalogRelease(
            spotify_id="studio",
            uri="spotify:album:studio",
            name="Studio Album",
            release_type="Album",
            release_date="2020-01-01",
            chronology_date="2020-01-01",
            total_tracks=10,
            identity="studio album",
            saved=True,
            plain=True,
            edition_rank=0,
            default=True,
        )
        live = api.discography.CatalogRelease(
            spotify_id="live",
            uri="spotify:album:live",
            name="Live Album",
            release_type="Live",
            release_date="2021-01-01",
            chronology_date="2021-01-01",
            total_tracks=12,
            identity="live album",
            saved=False,
            plain=True,
            edition_rank=0,
            default=False,
        )
        artist_candidates = (
            api.something_old.SpotifyArtistCandidate(
                spotify_id="artist",
                name="Artist",
                uri="spotify:artist:artist",
                popularity=70,
                followers=1000,
                search_rank=1,
            ),
            api.something_old.SpotifyArtistCandidate(
                spotify_id="artist-2",
                name="Artist",
                uri="spotify:artist:artist-2",
                popularity=20,
                followers=50,
                search_rank=2,
            ),
        )
        return cls(
            artist=artist,
            artist_candidates=artist_candidates,
            live=live,
            received=received,
            studio=studio,
        )

    def _assert_artist_pending(
        self, artist_pending: Any, client: TestClient, job_id: Any
    ) -> None:
        """Verify the original artist pending contract.

        Args:
            artist_pending: Original artist pending observation.
            client: Original client observation.
            job_id: Original job id observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert artist_pending["kind"] == "artist"
        assert artist_pending["queue"] == "Memory Lane"
        assert artist_pending["artist_candidates"][0] == {
            "spotify_id": "artist",
            "name": "Artist",
            "popularity": 70,
            "followers": 1000,
        }
        assert (
            client.post(
                f"/commands/plan-discographies-jobs/{job_id}/choice",
                json={"choice": "missing"},
            ).status_code
            == 400
        )
        assert (
            client.post(
                f"/commands/plan-discographies-jobs/{job_id}/choice",
                json={"choice": "artist"},
            ).status_code
            == 200
        )

    def _assert_pending(self, client: TestClient, job_id: Any, pending: Any) -> None:
        """Verify the original pending contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.
            pending: Original pending observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert pending["kind"] == "releases"
        assert pending["default_release_ids"] == ["studio"]
        assert pending["releases"][1]["release_type"] == "Live"
        assert (
            client.post(
                f"/commands/plan-discographies-jobs/{job_id}/choice",
                json={"choice": "select", "release_ids": ["missing"]},
            ).status_code
            == 400
        )

    def _assert_confirmation(self, confirmation: Any) -> None:
        """Verify the original confirmation contract.

        Args:
            confirmation: Original confirmation observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert confirmation["discography_pending_choice"]["kind"] == "confirm"
        assert confirmation["discography_total_releases"] == 2
        assert confirmation["discography_days"] == 1
        assert confirmation["discography_start_queue"] == "The Requeue"
        assert confirmation["discography_next_queue"] == "Memory Lane"
        assert confirmation["discography_results"][0]["release_names"] == [
            "Studio Album",
            "Live Album",
        ]

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["selected_ids"] == ("studio", "live")
        assert self.received["mapped_artist_id"] == "artist"
        assert self.received["playlist_ids"] == {
            "newfoundland": "nf",
            "memory_lane": "ml",
            "requeue": "rq",
        }
        assert self.received["queue_3_playlist_id"] == "q3"
        assert self.received["applied_plan"].total_releases == 2
        assert completed["discography_removed_artists"] == 1
        assert completed["discography_removed_markers"] == 2
        assert client.get("/commands/plan-discographies-jobs").json() == []


@dataclass
class RequeueForADreamWebJobReportsTransitionAndReconnectsScenario:
    """Retain the original requeue for a dream web job reports transition and reconnects
    fixture.

    Args:
        entered: Original entered observation or resource.
        received: Original received observation or resource.
        release_worker: Original release worker observation or resource.
    """

    entered: Event
    received: dict[str, object]
    release_worker: Event

    def run(
        self, spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.requeue_for_a_dream.RequeueForADreamSummary:
        """Execute the original run mock boundary.

        Args:
            spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify, playlist_id=playlist_id, dry_run=kwargs["dry_run"]
        )
        kwargs["progress_callback"].echo("Loading Artist's discography")
        self.entered.set()
        assert self.release_worker.wait(2)
        return api.requeue_for_a_dream.RequeueForADreamSummary(
            recorded_at=datetime(2026, 8, 4, tzinfo=UTC),
            playlist_id=playlist_id,
            dry_run=True,
            action="advance",
            playlist_length_before=4,
            playlist_length_after=4,
            artist="Artist",
            source_track="Current Track",
            source_release="First Album",
            target_track="Next Track",
            target_release="Second Album",
            target_release_type="Album",
            target_release_date="2002-03-04",
        )

    @classmethod
    def example(cls) -> RequeueForADreamWebJobReportsTransitionAndReconnectsScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        entered = Event()
        release_worker = Event()
        received: dict[str, object] = {}
        return cls(entered=entered, received=received, release_worker=release_worker)

    def _assert_job_id(self, client: TestClient, job_id: Any) -> None:
        """Verify the original job id contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.entered.wait(2)
        assert [
            job["job_id"]
            for job in client.get("/commands/flush-requeue-for-a-dream-jobs").json()
        ] == [job_id]

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["playlist_id"] == "0000000000000000000000"
        assert self.received["dry_run"] is True
        assert completed["requeue_action"] == "advance"
        assert completed["requeue_artist"] == "Artist"
        assert completed["requeue_source_release"] == "First Album"
        assert completed["requeue_target_track"] == "Next Track"
        assert completed["requeue_target_release"] == "Second Album"
        assert completed["requeue_target_release_type"] == "Album"
        assert completed["playlist_length_before"] == 4
        assert completed["playlist_length_after"] == 4
        assert any(
            entry["message"] == "Loading Artist's discography"
            for entry in completed["logs"]
        )
        assert client.get("/commands/flush-requeue-for-a-dream-jobs").json() == []


@dataclass
class PalaceOfMemoryWebJobReportsResultsAndReconnectsScenario:
    """Retain the original palace of memory web job reports results and reconnects
    fixture.

    Args:
        entered: Original entered observation or resource.
        received: Original received observation or resource.
        release_worker: Original release worker observation or resource.
    """

    entered: Event
    received: dict[str, object]
    release_worker: Event

    def __call__(
        self, spotify: Any, playlist_id: Any, **kwargs: Any
    ) -> api.palace_of_memory.PalaceOfMemorySummary:
        """Execute the original run mock boundary.

        Args:
            spotify: Original external mock argument.
            playlist_id: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(
            spotify=spotify,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
            alphabetical_start=kwargs["alphabetical_start"],
        )
        kwargs["progress_callback"].echo("Refreshing saved albums at offset 50")
        self.entered.set()
        assert self.release_worker.wait(2)
        spotify_album = api.palace_of_memory.SpotifyAlbum(
            spotify_id="album-id",
            uri="spotify:album:album-id",
            artist="Palace Artist",
            album="Palace Album",
            saved=True,
            similarity=1.0,
        )
        first_track = api.palace_of_memory.SpotifyFirstTrack(
            spotify_id="track-id", uri="spotify:track:track-id", name="Opening Track"
        )
        return api.palace_of_memory.PalaceOfMemorySummary(
            generated_at=datetime(2026, 8, 4, 15, 30, tzinfo=UTC),
            playlist_id=playlist_id,
            dry_run=True,
            cutoff_date=date(2025, 12, 31),
            available_dates=5092,
            alphabetical_start_index=5,
            alphabetical_next_index=10,
            alphabetical_cursor_overridden=True,
            playlist_length_before=7,
            playlist_length_after=8,
            album_refresh=api.palace_of_memory.SavedAlbumRefresh(
                checked_at=datetime(2026, 8, 4, tzinfo=UTC),
                previous=3982,
                current=3983,
                added=1,
                removed=0,
                skipped=0,
                persisted=True,
                backup_path="/tmp/albums-backup.json",
            ),
            results=(
                api.palace_of_memory.PalaceAlbumResult(
                    source="alphabetical",
                    artist="Palace Artist",
                    album="Palace Album",
                    spotify_album=spotify_album,
                    first_track=first_track,
                    action="added",
                ),
            ),
        )

    @classmethod
    def example(cls) -> PalaceOfMemoryWebJobReportsResultsAndReconnectsScenario:
        """Construct the original fixed scenario inputs.

        Returns:
            Original request, choice and expected-result observations."""
        entered = Event()
        release_worker = Event()
        received: dict[str, object] = {}
        return cls(entered=entered, received=received, release_worker=release_worker)

    def _assert_job_id(self, client: TestClient, job_id: Any) -> None:
        """Verify the original job id contract.

        Args:
            client: Original client observation.
            job_id: Original job id observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.entered.wait(2)
        assert [
            job["job_id"]
            for job in client.get("/commands/fill-palace-of-memory-jobs").json()
        ] == [job_id]

    def _assert_completed(self, client: TestClient, completed: Any) -> None:
        """Verify the original completed contract.

        Args:
            client: Original client observation.
            completed: Original completed observation.

        Raises:
            AssertionError: An original response or accepted-effect contract differs."""
        assert self.received["playlist_id"] == "0000000000000000000000"
        assert self.received["dry_run"] is True
        assert self.received["alphabetical_start"] == "6"
        assert completed["palace_alphabetical_start_index"] == 5
        assert completed["palace_alphabetical_next_index"] == 10
        assert completed["palace_alphabetical_cursor_overridden"] is True
        assert completed["palace_cutoff_date"] == "2025-12-31"
        assert completed["palace_available_dates"] == 5092
        assert completed["palace_album_refresh"]["current"] == 3983
        assert completed["palace_results"][0]["first_track"] == "Opening Track"
        assert completed["playlist_length_before"] == 7
        assert completed["playlist_length_after"] == 8
        assert any(
            entry["message"] == "Refreshing saved albums at offset 50"
            for entry in completed["logs"]
        )
        assert client.get("/commands/fill-palace-of-memory-jobs").json() == []


@dataclass
class PalaceWebCanPersistOnlyCursorWithoutPlaylistConfigScenario:
    """Retain the original palace web can persist only cursor without playlist config
    fixture.
    """

    def set_cursor(
        self, _spotify: Any, position: Any, **kwargs: Any
    ) -> api.palace_of_memory.AlphabeticalCursorUpdate:
        """Execute the original set cursor mock boundary.

        Args:
            _spotify: Original external mock argument.
            position: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].echo("Refreshing the saved-album mirror")
        return api.palace_of_memory.AlphabeticalCursorUpdate(
            next_index=249,
            next_album=YourLibraryAlbum(
                artist="Cursor Artist",
                album="Cursor Album",
                uri="spotify:album:cursor-album",
            ),
            album_refresh=api.palace_of_memory.SavedAlbumRefresh(
                checked_at=datetime(2026, 8, 4, tzinfo=UTC),
                previous=3983,
                current=3983,
                added=0,
                removed=0,
                skipped=0,
                persisted=False,
                backup_path=None,
            ),
        )


@dataclass
class ScrobbleHistoryWebJobReportsRefreshSummaryScenario:
    """Retain the original scrobble history web job reports refresh summary fixture.

    Args:
        history: Original history observation or resource.
        received: Original received observation or resource.
    """

    history: tuple[object, ...]
    received: dict[str, object]

    def refresh(
        self, lastfm: Any, **kwargs: Any
    ) -> api.scrobble_history.ScrobbleHistorySummary:
        """Execute the original refresh mock boundary.

        Args:
            lastfm: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(lastfm=lastfm, **kwargs)
        kwargs["progress_callback"].echo("Fetching page 1 of 1 from Last.fm")
        return api.scrobble_history.ScrobbleHistorySummary(
            checked_at=datetime(2026, 8, 4, tzinfo=UTC),
            username="man-et-arms",
            history=self.history,
            export_scrobbles=10,
            legacy_scrobbles_added=1,
            live_scrobbles_added=1,
            dry_run=False,
            persisted=True,
            backup_path=Path("/tmp/scrobbles-backup.json.gz"),
        )


@dataclass
class AsyncAnalysisEndpointRunsBackgroundJobWithoutClientScenario:
    """Retain the original async analysis endpoint runs background job without client
    fixture.
    """

    def complete_export(self, **kwargs: Any) -> Any:
        """Execute the original complete export mock boundary.

        Args:
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].progress("albums", 2, 2, "Complete")
        return analysis_summary("async")


@dataclass
class SyncAnalysisEndpointUsesInjectedNoRetryClientScenario:
    """Retain the original sync analysis endpoint uses injected no retry client fixture.

    Args:
        calls: Original calls observation or resource.
    """

    calls: list[object]

    def complete_sync(self, spotify: Any, **_kwargs: Any) -> Any:
        """Execute the original complete sync mock boundary.

        Args:
            spotify: Original external mock argument.
            _kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.calls.append(spotify)
        spotify.event_callback.echo(
            "Switching Spotify credentials to app5 and refreshing its token."
        )
        return analysis_summary("sync")


@dataclass
class LiveMirrorRefreshEndpointSkipsArtistProgressScenario:
    """Retain the original live mirror refresh endpoint skips artist progress fixture.

    Args:
        calls: Original calls observation or resource.
    """

    calls: list[object]

    def complete_refresh(self, spotify: Any, **kwargs: Any) -> Any:
        """Execute the original complete refresh mock boundary.

        Args:
            spotify: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.calls.append((spotify, kwargs["full_rebuild"]))
        kwargs["progress_callback"].progress("albums", 2, 2, "Complete")
        kwargs["progress_callback"].progress("tracks", 3, 3, "Complete")
        return analysis_summary("mirrors")


@dataclass
class IndependentLiveMirrorRefreshEndpointScenario:
    """Retain the original independent live mirror refresh endpoint fixture.

    Args:
        calls: Original calls observation or resource.
    """

    calls: list[object]

    def complete_resource(
        self, spotify: Any, selected_resource: Any, **kwargs: Any
    ) -> api.library_analysis.LibrarySyncSummary:
        """Execute the original complete resource mock boundary.

        Args:
            spotify: Original external mock argument.
            selected_resource: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.calls.append((spotify, selected_resource, kwargs["full_rebuild"]))
        kwargs["progress_callback"].progress(selected_resource, 2, 2, "Complete")
        return api.library_analysis.LibrarySyncSummary(
            run_id="run-1",
            mode="mirrors",
            backup_dir="/tmp/mirrors/run-1",
            resources=(),
        )


@dataclass
class LiveAnalysisJobCanBeCancelledDuringRetryWaitScenario:
    """Retain the original live analysis job can be cancelled during retry wait fixture.

    Args:
        http_status: Original http status observation or resource.
    """

    http_status: int | None

    def wait_for_server(self, _spotify: Any, **kwargs: Any) -> Any:
        """Execute the original wait for server mock boundary.

        Args:
            _spotify: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        keep_waiting = kwargs["retry_wait"].wait(
            api.library_analysis.RetryNotice(
                http_status=self.http_status,
                operation="reading artists",
                attempt=1,
                delay_seconds=60,
            )
        )
        if not keep_waiting:
            raise api.library_analysis.LibraryAnalysisCancelledError("Paused")
        return analysis_summary("sync")


@dataclass
class ActiveAnalysisJobsCanBeRestoredAfterReloadScenario:
    """Retain the original active analysis jobs can be restored after reload fixture.

    Args:
        release: Original release observation or resource.
    """

    release: api.Event

    def blocked_export(self, **kwargs: Any) -> Any:
        """Execute the original blocked export mock boundary.

        Args:
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["echo"].echo("Still reading exported albums.")
        self.release.wait(2)
        return analysis_summary("async")


@dataclass
class NewYearWebJobRoutesAndErrorsScenario:
    """Retain the original new year web job routes and errors fixture.

    Args:
        outcome: Original outcome observation or resource.
        received: Original received observation or resource.
    """

    outcome: Any
    received: dict[str, Any]

    def routine(
        self, sp: Any, lastfm: Any, config: Any, **kwargs: Any
    ) -> dict[str, Any]:
        """Execute the original routine mock boundary.

        Args:
            sp: Original external mock argument.
            lastfm: Original external mock argument.
            config: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.received.update(kwargs)
        kwargs["echo"].echo("Ranking annual charts")
        if self.outcome == "failed":
            raise RuntimeError("missing yearly source")
        if self.outcome == "cancelled":
            raise api.scrobble_history.ScrobbleHistoryCancelledError("cancelled")
        return {"year": 2025, "dry_run": True, "plan": {}}
