"""Tests for the FastAPI interface with isolated Spotify and file dependencies."""

from datetime import UTC
from datetime import date
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from time import sleep
from types import SimpleNamespace

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
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from spotify_manager.models.your_library import YourLibraryFile
from spotify_manager.models.your_library import YourLibraryTrack


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
    state_access = api.get_state_service().namespace(
        "release_check",
        api.release_check._default_state,
        api.release_check.validate_state,
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
    monkeypatch.setattr(api, "RELEASE_CHECK_STATE_PATH", state_path)
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
    from spotify_manager import api

    albums = tmp_path / "albums_total_new.json"
    tracks = tmp_path / "liked_tracks_total.json"
    artists = tmp_path / "artists_total.json"
    scrobbles = tmp_path / "lastfmstats-man-et-arms.json"
    albums.write_text("[]")
    artists.write_text("[]")
    scrobbles.write_text("{}")
    monkeypatch.setattr(
        api,
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
    from spotify_manager import api

    monkeypatch.setattr(api, "count_artists_in_library", lambda: 42)
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
    from spotify_manager import api

    calls: list[tuple[str, object | None]] = []
    monkeypatch.setattr(
        api,
        "compare_your_library_and_all_albums",
        lambda: calls.append(("compare", None)),
    )
    monkeypatch.setattr(
        api,
        "convert_your_library_file",
        lambda spotify: calls.append(("convert", spotify)),
    )
    monkeypatch.setattr(
        api,
        "run_monthly_routines",
        lambda spotify: calls.append(("monthly", spotify)),
    )
    monkeypatch.setattr(
        api,
        "update_total_album_list",
        lambda spotify, just_update: (
            calls.append((f"update:{just_update}", spotify)) or [1, 2]
        ),
    )
    monkeypatch.setattr(
        api,
        "restore_your_library_from_file",
        lambda spotify: calls.append(("restore", spotify)),
    )
    monkeypatch.setattr(
        api,
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
    from spotify_manager import api

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(api, "get_live_artist_library_stats", fail)

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

    monkeypatch.setattr(api, "evaluate_album_live", fail)

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
    from spotify_manager import api

    def fail(*_args: object, **_kwargs: object) -> None:
        raise SpotifyException(status_code, -1, "Spotify failed")

    monkeypatch.setattr(api, "get_live_artist_library_stats", fail)

    response = client.get("/artists/stats", params={"name": "Artist"})

    assert response.status_code == expected_status
    assert f"HTTP {status_code}" in response.json()["detail"]


def test_spotify_lookup_rate_limit_returns_retry_header(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spotify_manager import api

    def fail(*_args: object, **_kwargs: object) -> None:
        raise SpotifyException(
            429,
            -1,
            "rate limited",
            headers={"Retry-After": "120"},
        )

    monkeypatch.setattr(api, "get_live_artist_library_stats", fail)

    response = client.get("/artists/stats", params={"name": "Artist"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "120"
    assert "in 2 minutes" in response.json()["detail"]


@pytest.mark.parametrize(
    ("path", "reference", "message"),
    [
        ("/artists/stats", "spotify:artist:bad", "invalid Spotify artist URI"),
        ("/albums/evaluation", "spotify:album:bad", "invalid Spotify album URI"),
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

    monkeypatch.setattr(api, "evaluate_album_live", fail)

    response = client.get("/albums/evaluation", params={"name": "Album"})

    assert response.status_code == 502
    assert "could not be reached" in response.json()["detail"]


def test_cached_dependency_factories_use_expected_client_modes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    clients = iter([object(), object(), object()])
    monkeypatch.setattr(
        api,
        "get_spotipy_client",
        lambda **kwargs: calls.append(kwargs) or next(clients),
    )
    monkeypatch.setattr(api, "load_your_library_file", _library)
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
    monkeypatch.setattr(api, "_MAX_ANALYSIS_LOGS", 2)
    monkeypatch.setattr(api, "_MAX_BLAST_LOGS", 2)

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
    monkeypatch.setattr(api, "Settings", lambda: settings)

    response = client.post(path)

    assert response.status_code == 500
    assert "not configured" in response.json()["detail"].casefold()


def test_blast_from_the_past_endpoint_runs_background_job(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    received = {}
    scrobble = api.blast_from_past.Scrobble(
        track="Track",
        artist="Artist",
        album="Album",
        timestamp_ms=1,
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

    def complete(spotify, playlist_id, **kwargs):
        received.update(
            spotify=spotify,
            playlist_id=playlist_id,
            count=kwargs["count"],
            max_playlist_length=kwargs["max_playlist_length"],
        )
        kwargs["progress_callback"]("Searching Spotify track 1/1")
        return api.blast_from_past.BlastFromPastSpotifySummary(
            playlist_id=playlist_id,
            requested_count=10,
            playlist_length_before=4,
            playlist_length_after=5,
            batch=batch,
            results=(
                api.blast_from_past.SpotifySelectionResult(
                    selection=selection,
                    match=match,
                    qualifying_matches=1,
                    action="added",
                ),
            ),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(blast_from_the_past_playlist="spotify:playlist:blast"),
    )
    monkeypatch.setattr(
        api.blast_from_past,
        "add_blast_from_past_to_spotify",
        complete,
    )

    response = client.post("/commands/blast-from-the-past")

    assert response.status_code == 202
    result = wait_for_blast_status(
        client,
        response.json()["job_id"],
        {"completed"},
    )
    assert received["playlist_id"] == "blast"
    assert received["count"] == 10
    assert received["max_playlist_length"] is None
    assert result["added"] == 1
    assert result["playlist_length_before"] == 4
    assert result["playlist_length_after"] == 5
    assert result["random_org_timestamp"] == "2026-07-22T13:00:52+00:00"
    assert result["selections"][0]["liked"] is True
    assert result["selections"][0]["album_similarity"] == 0.2
    assert any(
        entry["message"] == "Searching Spotify track 1/1" for entry in result["logs"]
    )


def test_blast_from_the_past_endpoint_rejects_both_limits(
    client: TestClient,
) -> None:
    response = client.post(
        "/commands/blast-from-the-past",
        params={"count": 2, "max_playlist_length": 10},
    )

    assert response.status_code == 400
    assert "either count or max_playlist_length" in response.json()["detail"]


def test_daily_mind_radio_endpoint_runs_background_job(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    scrobble = api.blast_from_past.Scrobble(
        track="Track",
        artist="Artist",
        album="Album",
        timestamp_ms=1,
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

    def complete(_spotify, playlist_id, **kwargs):
        kwargs["progress_callback"]("Searching Spotify track 1/1")
        return api.daily_mind_radio.DailyMindRadioSpotifySummary(
            playlist_id=playlist_id,
            batch=batch,
            playlist_length_before=2,
            playlist_length_after=3,
            results=(
                api.blast_from_past.SpotifySelectionResult(
                    selection=selection,
                    match=match,
                    qualifying_matches=1,
                    action="added",
                ),
            ),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(daily_mind_radio_playlist="spotify:playlist:daily"),
    )
    monkeypatch.setattr(
        api.daily_mind_radio,
        "add_daily_mind_radio_to_spotify",
        complete,
    )

    response = client.post("/commands/daily-mind-radio")

    assert response.status_code == 202
    result = wait_for_daily_mind_radio_status(
        client,
        response.json()["job_id"],
        {"completed"},
    )
    assert result["command"] == "daily_mind_radio"
    assert result["added"] == 1
    assert result["playlist_length_before"] == 2
    assert result["playlist_length_after"] == 3
    assert result["target_dates"] == ["2025-07-22", "2020-07-22"]
    assert result["missing_dates"] == ["2020-07-22"]
    assert result["random_org_timestamp"] == "2026-07-22T13:00:52+00:00"
    assert result["selections"][0]["selected_date"] == "2025-07-22"
    assert any(
        entry["message"] == "Searching Spotify track 1/1" for entry in result["logs"]
    )


def test_active_daily_mind_radio_job_can_be_restored(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    release = api.Event()
    batch = api.daily_mind_radio.DailyMindRadioBatch(
        generated_at=None,
        target_dates=(date(2025, 7, 22),),
        missing_dates=(date(2025, 7, 22),),
        selections=(),
    )

    def blocked(_spotify, playlist_id, **kwargs):
        kwargs["progress_callback"]("Reading anniversary dates")
        release.wait(2)
        return api.daily_mind_radio.DailyMindRadioSpotifySummary(
            playlist_id=playlist_id,
            batch=batch,
            playlist_length_before=None,
            playlist_length_after=None,
            results=(),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(daily_mind_radio_playlist="daily"),
    )
    monkeypatch.setattr(
        api.daily_mind_radio,
        "add_daily_mind_radio_to_spotify",
        blocked,
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
    wait_for_daily_mind_radio_status(
        client,
        started.json()["job_id"],
        {"completed"},
    )
    assert client.get("/commands/daily-mind-radio-jobs").json() == []


def test_found_art_endpoint_runs_background_job_with_requested_count(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

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

    def complete(spotify, lastfm, playlist_id, **kwargs):
        received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlist_id=playlist_id,
            count=kwargs["count"],
        )
        kwargs["progress_callback"]("Getting Last.fm neighbors for seed 1/1")
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
                    candidate=candidate,
                    match=match,
                    action="added",
                ),
            ),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            found_art_playlist="spotify:playlist:found",
            lastfm_api_key="lastfm-key",
            lastfm_username="lastfm-user",
        ),
    )
    monkeypatch.setattr(api.found_art, "run_found_art", complete)

    response = client.post("/commands/found-art", params={"count": 7})

    assert response.status_code == 202
    result = wait_for_found_art_status(
        client,
        response.json()["job_id"],
        {"completed"},
    )
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
    assert result["found_art_results"][0]["spotify_match"] == (
        "Recommendation Artist - Recommendation Track - Recommendation Album"
    )
    assert any(
        entry["message"] == "Getting Last.fm neighbors for seed 1/1"
        for entry in result["logs"]
    )


def test_sauvignon_web_job_waits_for_album_choice_and_completes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def complete(spotify, lastfm, playlist_id, choice_reader, **kwargs):
        received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlist_id=playlist_id,
            count=kwargs["count"],
            max_playlist_length=kwargs["max_playlist_length"],
            seed_count=kwargs["seed_count"],
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"]("Resolving album recommendations")
        choice = choice_reader(recommendation, recommendation.options)
        received["choice"] = choice
        chosen = second_option if choice == second_option.spotify_id else first_option
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
                    recommendation=recommendation,
                    album=chosen,
                    first_track=api.sauvignon.FirstTrack(
                        "first",
                        "spotify:track:first",
                        "Opening Track",
                    ),
                    action="would add",
                ),
            ),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            sauvignon_terre_neuve_playlist="spotify:playlist:sauvignon",
            lastfm_api_key="lastfm-key",
            lastfm_username="lastfm-user",
        ),
    )
    monkeypatch.setattr(api.sauvignon, "fill_sauvignon_from_lastfm", complete)

    response = client.post(
        "/commands/fill-sauvignon-from-lastfm",
        params={"dry_run": True},
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    waiting = wait_for_sauvignon_status(client, job_id, {"waiting"})
    assert waiting["sauvignon_pending_choice"]["album"] == "Recommendation Album"
    assert [
        option["spotify_id"]
        for option in waiting["sauvignon_pending_choice"]["options"]
    ] == ["plain", "alternate"]
    assert [
        job["job_id"]
        for job in client.get("/commands/fill-sauvignon-from-lastfm-jobs").json()
    ] == [job_id]

    choice = client.post(
        f"/commands/fill-sauvignon-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "alternate"},
    )
    assert choice.status_code == 200

    result = wait_for_sauvignon_status(client, job_id, {"completed"})
    assert received["playlist_id"] == "sauvignon"
    assert received["count"] is None
    assert received["max_playlist_length"] == 20
    assert received["seed_count"] == 30
    assert received["dry_run"] is True
    assert received["choice"] == "alternate"
    assert result["command"] == "fill_sauvignon_from_lastfm"
    assert result["added"] == 1
    assert result["sauvignon_history_albums"] == 400
    assert result["sauvignon_track_candidate_count"] == 100
    assert result["sauvignon_album_candidate_count"] == 25
    assert result["sauvignon_results"][0]["spotify_album_id"] == "alternate"
    assert result["sauvignon_results"][0]["first_track"] == "Opening Track"
    assert client.get("/commands/fill-sauvignon-from-lastfm-jobs").json() == []


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
        api,
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
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

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

    def flush(
        spotify,
        new_playlist_id,
        queue_playlist_id,
        great_playlist_id,
        unlucky_playlist_id,
        newfoundland_playlist_id,
        **kwargs,
    ):
        received.update(
            spotify_type=type(spotify).__name__,
            new_playlist_id=new_playlist_id,
            queue_playlist_id=queue_playlist_id,
            great_playlist_id=great_playlist_id,
            unlucky_playlist_id=unlucky_playlist_id,
            newfoundland_playlist_id=newfoundland_playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"](0, 1, "Reviewing Artist")
        choice = kwargs["choice_reader"]("Artist", (release,))
        received["choice"] = choice
        kwargs["echo"](f"Selected {choice}")
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            new_kids_on_the_block_playlist="spotify:playlist:newkids",
            the_queue_2_playlist="spotify:playlist:queue2",
            great_discoveries_2026_playlist="spotify:playlist:great",
            unlucky_ones_playlist="spotify:playlist:unlucky",
            discography_newfoundland_playlist="spotify:playlist:newfoundland",
        ),
    )
    monkeypatch.setattr(api.new_kids, "flush_new_kids", flush)

    started = client.post(
        "/commands/flush-new-kids",
        params={"dry_run": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_new_kids_status(client, job_id, {"waiting"})
    assert waiting["dry_run"] is True
    assert waiting["new_kids_pending_choice"]["artist"] == "Artist"
    assert waiting["new_kids_pending_choice"]["releases"] == [
        {
            "spotify_id": "release",
            "name": "Ranked Album",
            "release_type": "Album",
            "release_date": "2024-01-01",
            "total_tracks": 9,
            "popularity": 73,
            "top_track_rank": 2,
            "saved": True,
        }
    ]
    assert [
        job["job_id"] for job in client.get("/commands/flush-new-kids-jobs").json()
    ] == [job_id]

    choice = client.post(
        f"/commands/flush-new-kids-jobs/{job_id}/choice",
        json={"choice": "release"},
    )

    assert choice.status_code == 200
    completed = wait_for_new_kids_status(client, job_id, {"completed"})
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
    assert completed["processed"] == 1
    assert completed["playlist_length_before"] == 9
    assert completed["playlist_length_after"] == 10
    assert completed["new_kids_resumed"] is True
    assert completed["new_kids_results"][0]["target_track"] == "Opening Track"
    assert completed["new_kids_prefill"][0]["artist"] == "Queue Artist"
    assert any(entry["message"] == "Selected release" for entry in completed["logs"])
    assert client.get("/commands/flush-new-kids-jobs").json() == []


def test_queue_fill_web_job_waits_for_artist_mapping(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def fill(spotify, lastfm, playlists, choice_reader, **kwargs):
        received.update(
            spotify_type=type(spotify).__name__,
            lastfm_username=lastfm.username,
            queue=playlists.queue,
            count=kwargs["count"],
            seed_count=kwargs["seed_count"],
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"](0, 1, "Resolving Last.fm Artist")
        received["choice"] = choice_reader(recommendation, (artist,))
        kwargs["echo"]("Would add Spotify Artist - Queue Marker to The Queue.")
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
                    recommendation,
                    artist,
                    track,
                    "would add",
                    followed=True,
                ),
            ),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_playlist="spotify:playlist:queue",
            the_queue_2_playlist="spotify:playlist:queue2",
            new_kids_on_the_block_playlist="spotify:playlist:newkids",
            the_queue_3_playlist="spotify:playlist:queue3",
            unlucky_ones_playlist="spotify:playlist:unlucky",
            lastfm_api_key="lastfm-key",
            lastfm_username="lastfm-user",
        ),
    )
    monkeypatch.setattr(api.the_queue, "fill_queue_from_lastfm", fill)

    started = client.post(
        "/commands/fill-queue-from-lastfm",
        params={"count": 2, "seed_count": 30, "dry_run": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_queue_fill_status(client, job_id, {"waiting"})
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

    unavailable = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "missing-artist"},
    )
    empty_search = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "search:   "},
    )
    assert unavailable.status_code == 400
    assert empty_search.status_code == 400

    choice = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "artist-id"},
    )

    assert choice.status_code == 200
    completed = wait_for_queue_fill_status(client, job_id, {"completed"})
    assert received == {
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
    stale_choice = client.post(
        f"/commands/fill-queue-from-lastfm-jobs/{job_id}/choice",
        json={"choice": "artist-id"},
    )
    assert stale_choice.status_code == 409
    assert client.get("/commands/fill-queue-from-lastfm-jobs").json() == []


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
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, object] = {}

    def flush(spotify, playlists, **kwargs):
        received.update(
            spotify_type=type(spotify).__name__,
            queue=playlists.queue,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"](1, 1, "Completed Artist")
        kwargs["echo"]("Would promote Artist to Queue 2 with Opening.")
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_playlist="spotify:playlist:queue",
            the_queue_2_playlist="spotify:playlist:queue2",
            new_kids_on_the_block_playlist="spotify:playlist:newkids",
            the_queue_3_playlist="spotify:playlist:queue3",
            unlucky_ones_playlist="spotify:playlist:unlucky",
        ),
    )
    monkeypatch.setattr(api.the_queue, "flush_queue", flush)

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
    assert completed["queue_flush_results"][0]["target_release"] == (
        "Established Album"
    )
    assert completed["queue_flush_results"][0]["top_liked_tracks"] == 5
    assert client.get("/commands/flush-queue-jobs").json() == []


def test_queue_2_web_job_waits_for_and_applies_release_choice(
    client: TestClient,
    monkeypatch,
) -> None:
    """Queue 2 should expose its shared release prompt and both list counts."""
    from spotify_manager import api

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

    def flush(
        spotify,
        new_playlist_id,
        queue_playlist_id,
        great_playlist_id,
        unlucky_playlist_id,
        newfoundland_playlist_id,
        **kwargs,
    ):
        received.update(
            spotify_type=type(spotify).__name__,
            new_playlist_id=new_playlist_id,
            queue_playlist_id=queue_playlist_id,
            great_playlist_id=great_playlist_id,
            unlucky_playlist_id=unlucky_playlist_id,
            newfoundland_playlist_id=newfoundland_playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"](0, 1, "Reviewing Artist")
        choice = kwargs["choice_reader"]("Artist", (release,))
        received["choice"] = choice
        kwargs["echo"](f"Selected {choice}")
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            new_kids_on_the_block_playlist="spotify:playlist:newkids",
            the_queue_2_playlist="spotify:playlist:queue2",
            great_discoveries_2026_playlist="spotify:playlist:great",
            unlucky_ones_playlist="spotify:playlist:unlucky",
            discography_newfoundland_playlist="spotify:playlist:newfoundland",
        ),
    )
    monkeypatch.setattr(api.new_kids, "flush_queue_2", flush)

    started = client.post(
        "/commands/flush-queue-2",
        params={"dry_run": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_queue_2_status(client, job_id, {"waiting"})
    assert waiting["command"] == "flush_queue_2"
    assert waiting["new_kids_pending_choice"]["artist"] == "Artist"
    assert [
        job["job_id"] for job in client.get("/commands/flush-queue-2-jobs").json()
    ] == [job_id]

    choice = client.post(
        f"/commands/flush-queue-2-jobs/{job_id}/choice",
        json={"choice": "release"},
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
    client: TestClient,
    monkeypatch,
) -> None:
    """Queue 3 should reconnect across both of its interactive choice types."""
    from spotify_manager import api

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

    def boundary_release(spotify_id: str, name: str, date: str):
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

    received: dict[str, object] = {}

    def flush(spotify, playlist_id, transition_reader, **kwargs):
        received.update(
            spotify_type=type(spotify).__name__,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"](0, 2, "Reviewing Artist")
        received["release_choice"] = transition_reader(
            source,
            boundary_release("current", "Current Release", "2020-01-01"),
            boundary_release("next", "Next Release", "2021-01-01"),
        )
        received["composer_choice"] = kwargs["composer_playlist_reader"](
            "Johann Sebastian Bach",
            (
                api.queue_3.OwnedPlaylist("bach-a", "Bach works", 120),
                api.queue_3.OwnedPlaylist("bach-b", "All of Bach", 3197),
            ),
        )
        kwargs["progress_callback"](2, 2, "Completed Queue 3")
        kwargs["echo"]("Queue 3 choices applied")
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            the_queue_3_playlist="spotify:playlist:queue3",
        ),
    )
    monkeypatch.setattr(api.queue_3, "flush_queue_3", flush)

    started = client.post(
        "/commands/flush-queue-3",
        params={"dry_run": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    release_wait = wait_for_queue_3_choice(client, job_id, "release")
    assert release_wait["queue_3_pending_choice"]["next_release"]["name"] == (
        "Next Release"
    )
    assert [
        job["job_id"] for job in client.get("/commands/flush-queue-3-jobs").json()
    ] == [job_id]

    release_response = client.post(
        f"/commands/flush-queue-3-jobs/{job_id}/choice",
        json={"choice": "advance"},
    )
    assert release_response.status_code == 200

    composer_wait = wait_for_queue_3_choice(client, job_id, "composer_playlist")
    assert [
        playlist["spotify_id"]
        for playlist in composer_wait["queue_3_pending_choice"]["playlists"]
    ] == ["bach-a", "bach-b"]
    composer_response = client.post(
        f"/commands/flush-queue-3-jobs/{job_id}/choice",
        json={"choice": "bach-b"},
    )
    assert composer_response.status_code == 200

    completed = wait_for_queue_3_status(client, job_id, {"completed"})
    assert received == {
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


def test_new_wine_web_job_waits_for_and_applies_release_choice(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

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

    def flush(
        spotify,
        new_playlist_id,
        sauvignon_playlist_id,
        **kwargs,
    ):
        received.update(
            spotify=spotify,
            new_playlist_id=new_playlist_id,
            sauvignon_playlist_id=sauvignon_playlist_id,
            wine_cellar_playlist_id=kwargs["wine_cellar_playlist_id"],
            dry_run=kwargs["dry_run"],
            no_discovery=kwargs["no_discovery"],
        )
        kwargs["progress_callback"](0, 1, "Reviewing Current Track")
        choice = kwargs["choice_reader"](source, (current, alternative))
        received["choice"] = choice
        kwargs["echo"](f"Selected {choice}")
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
                    source_track=source.name,
                    artist=source.primary_artist_name,
                    release=alternative.name,
                    release_type=alternative.release_type,
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            new_wine_from_old_bottles_playlist="spotify:playlist:new",
            sauvignon_terre_neuve_playlist="spotify:playlist:sauv",
            wine_cellar_playlist="spotify:playlist:cellar",
        ),
    )
    monkeypatch.setattr(api.new_wine, "flush_new_wine", flush)

    started = client.post(
        "/commands/flush-new-wine",
        params={"dry_run": "true", "no_discovery": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_new_wine_status(client, job_id, {"waiting"})
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

    choice = client.post(
        f"/commands/flush-new-wine-jobs/{job_id}/choice",
        json={"choice": "alternative"},
    )

    assert choice.status_code == 200
    completed = wait_for_new_wine_status(client, job_id, {"completed"})
    assert received["new_playlist_id"] == "new"
    assert received["sauvignon_playlist_id"] == "sauv"
    assert received["wine_cellar_playlist_id"] == "cellar"
    assert received["dry_run"] is True
    assert received["no_discovery"] is True
    assert received["choice"] == "alternative"
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
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

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

    def flush(spotify, playlist_id, **kwargs):
        received.update(
            spotify=spotify,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"](0, 1, "Reviewing Source Track")
        received["track_choice"] = kwargs["action_reader"](
            source,
            target,
            first_release,
        )
        received["release_order"] = kwargs["order_reader"](
            "2021-01-01",
            (first_release, second_release),
        )
        kwargs["completion_notifier"](source)
        kwargs["echo"]("Slow Listening choices applied")
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
                    source_track=source.name,
                    source_release=source_release.name,
                    artist=source.primary_artist_name,
                    action="advance",
                    target_track=target.name,
                    target_release=first_release.name,
                    skipped_candidates=("Skipped Track (Source Album)",),
                    dry_run=kwargs["dry_run"],
                ),
            ),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            slow_listening_playlist="spotify:playlist:slow",
        ),
    )
    monkeypatch.setattr(
        api.slow_listening,
        "flush_slow_listening",
        flush,
    )

    started = client.post(
        "/commands/flush-slow-listening",
        params={"dry_run": "false"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    track_waiting = wait_for_slow_listening_status(client, job_id, {"waiting"})
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

    track_choice = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={"choice": "advance"},
    )
    assert track_choice.status_code == 200

    order_waiting = wait_for_slow_listening_status(client, job_id, {"waiting"})
    pending_order = order_waiting["slow_listening_pending_choice"]
    assert pending_order["kind"] == "release_order"
    assert [release["spotify_id"] for release in pending_order["releases"]] == [
        "first-release",
        "second-release",
    ]

    invalid_order = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={
            "choice": "order",
            "order": ["first-release", "first-release"],
        },
    )
    assert invalid_order.status_code == 400

    order_choice = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={
            "choice": "order",
            "order": ["second-release", "first-release"],
        },
    )
    assert order_choice.status_code == 200

    completion_waiting = wait_for_slow_listening_status(
        client,
        job_id,
        {"waiting"},
    )
    assert completion_waiting["slow_listening_pending_choice"]["kind"] == "completion"

    completion_choice = client.post(
        f"/commands/flush-slow-listening-jobs/{job_id}/choice",
        json={"choice": "continue"},
    )
    assert completion_choice.status_code == 200

    completed = wait_for_slow_listening_status(client, job_id, {"completed"})
    assert received["playlist_id"] == "slow"
    assert received["dry_run"] is False
    assert received["track_choice"] == "advance"
    assert received["release_order"] == (
        "second-release",
        "first-release",
    )
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


def test_slow_listening_web_job_retries_a_connection_reset(
    client: TestClient,
    monkeypatch,
) -> None:
    from requests.exceptions import ConnectionError as RequestsConnectionError

    from spotify_manager import api

    attempts = 0
    retry_spotify_server_errors = api.review_album_limits.retry_spotify_server_errors

    def retry_without_wait(*args, **kwargs):
        kwargs["sleep"] = lambda _seconds: None
        return retry_spotify_server_errors(*args, **kwargs)

    def flush(_spotify, _playlist_id, **kwargs):
        nonlocal attempts

        def load_playlist() -> None:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RequestsConnectionError(
                    "Connection aborted.",
                    ConnectionResetError(104, "Connection reset by peer"),
                )

        kwargs["retry_call"](
            load_playlist,
            "loading the Slow Listening playlist",
        )
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            slow_listening_playlist="spotify:playlist:slow",
        ),
    )
    monkeypatch.setattr(
        api.review_album_limits,
        "retry_spotify_server_errors",
        retry_without_wait,
    )
    monkeypatch.setattr(api.slow_listening, "flush_slow_listening", flush)

    started = client.post(
        "/commands/flush-slow-listening",
        params={"dry_run": "true"},
    )

    assert started.status_code == 202
    completed = wait_for_slow_listening_status(
        client,
        started.json()["job_id"],
        {"completed"},
    )
    assert attempts == 2
    assert completed["detail"] == (
        "0/0 processed; 0 advanced, 0 artists completed, 0 skipped."
    )
    assert any(
        entry["message"].startswith(
            "Spotify connection interrupted while loading the Slow Listening "
            "playlist. Retrying in 10 seconds (at "
        )
        for entry in completed["logs"]
    )


def test_something_old_web_job_handles_all_interactive_choices(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    artist = api.something_old.GoldenOldieArtist(
        artist="Old Artist",
        scrobbles=50,
        average_scrobble_ms=1_000,
        first_scrobble_ms=1,
        last_scrobble_ms=2_000,
        top_tracks=(),
    )
    first_spotify_artist = api.something_old.SpotifyArtistCandidate(
        spotify_id="artist-one",
        name="Old Artist",
        uri="spotify:artist:artist-one",
        popularity=60,
        followers=10_000,
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

    def run(spotify, lastfm, playlist_id, **kwargs):
        received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"]("Calculating Golden Oldies")
        received["artist_choice"] = kwargs["artist_choice_reader"](
            artist,
            (first_spotify_artist, second_spotify_artist),
        )
        received["mode_choice"] = kwargs["mode_reader"](
            artist,
            first_spotify_artist,
        )
        received["album_choice"] = kwargs["album_choice_reader"](
            artist,
            (release,),
        )
        return api.something_old.SomethingOldSummary(
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            playlist_id=playlist_id,
            playlist_length_before=0,
            playlist_length_after=0,
            dry_run=True,
            action="would add",
            history_refresh=history_summary,
            ranking_preview=(artist,),
            artist=artist,
            spotify_artist=first_spotify_artist,
            mode="album",
            release=release,
            tracks=(selected_track,),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            something_old_new_playlist=("spotify:playlist:0000000000000000000000"),
            lastfm_api_key="lastfm-key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(api.something_old, "run_something_old", run)

    started = client.post(
        "/commands/something-old",
        params={"dry_run": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    artist_waiting = wait_for_something_old_status(client, job_id, {"waiting"})
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

    invalid_artist = client.post(
        f"/commands/something-old-jobs/{job_id}/choice",
        json={"choice": "not-an-artist"},
    )
    assert invalid_artist.status_code == 400
    artist_choice = client.post(
        f"/commands/something-old-jobs/{job_id}/choice",
        json={"choice": "artist-one"},
    )
    assert artist_choice.status_code == 200

    mode_waiting = wait_for_something_old_status(client, job_id, {"waiting"})
    assert mode_waiting["something_old_pending_choice"]["kind"] == "mode"
    assert mode_waiting["something_old_pending_choice"]["scrobbles"] == 50
    mode_choice = client.post(
        f"/commands/something-old-jobs/{job_id}/choice",
        json={"choice": "album"},
    )
    assert mode_choice.status_code == 200

    album_waiting = wait_for_something_old_status(client, job_id, {"waiting"})
    pending_album = album_waiting["something_old_pending_choice"]
    assert pending_album["kind"] == "album"
    assert pending_album["releases"][0]["spotify_id"] == "release-id"
    album_choice = client.post(
        f"/commands/something-old-jobs/{job_id}/choice",
        json={"choice": "release-id"},
    )
    assert album_choice.status_code == 200

    completed = wait_for_something_old_status(client, job_id, {"completed"})
    assert received["playlist_id"] == "0000000000000000000000"
    assert received["dry_run"] is True
    assert received["artist_choice"] == "artist-one"
    assert received["mode_choice"] == "album"
    assert received["album_choice"] == "release-id"
    assert completed["something_old_action"] == "would add"
    assert completed["something_old_artist"] == "Old Artist"
    assert completed["something_old_release"] == "Old Album"
    assert completed["something_old_tracks"][0]["track"] == "Old Track"
    assert completed["history_scrobbles"] == 50
    assert completed["live_scrobbles_added"] == 1
    assert any(
        entry["message"] == "Calculating Golden Oldies" for entry in completed["logs"]
    )
    assert client.get("/commands/something-old-jobs").json() == []


def test_release_check_web_job_handles_search_mapping_and_release_choice(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    artist = api.release_check.RankedArtist(
        key="lastfm artist",
        name="Last.fm Artist",
        scrobbles=250,
        rank=12,
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
        followers=10_000,
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

    def run(spotify, lastfm, playlists, **kwargs):
        received.update(
            spotify=spotify,
            lastfm=lastfm,
            playlists=playlists,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"](0, 1, "Resolving release-check artist")
        received["search_choice"] = kwargs["artist_choice_reader"](
            artist,
            (first_candidate,),
        )
        received["artist_choice"] = kwargs["artist_choice_reader"](
            artist,
            (selected_candidate,),
        )
        received["release_choice"] = kwargs["release_choice_reader"](
            artist,
            release,
            track,
            ("Wine Cellar", "New Vintage"),
            False,
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
            history_refresh=None,
            results=(result,),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            wine_cellar_playlist="spotify:playlist:0000000000000000000001",
            new_vintage_playlist="spotify:playlist:0000000000000000000002",
            lastfm_api_key="lastfm-key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(api.release_check, "run_release_check", run)

    started = client.post(
        "/commands/check-new-releases",
        params={"dry_run": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    first_mapping = wait_for_release_check_status(client, job_id, {"waiting"})
    assert first_mapping["release_check_pending_choice"]["kind"] == "artist"
    assert first_mapping["release_check_pending_choice"]["artist_rank"] == 12
    assert (
        client.post(
            f"/commands/check-new-releases-jobs/{job_id}/choice",
            json={"choice": "search:"},
        ).status_code
        == 400
    )
    searched = client.post(
        f"/commands/check-new-releases-jobs/{job_id}/choice",
        json={"choice": "search:Lastfm Artist Band"},
    )
    assert searched.status_code == 200

    second_mapping = wait_for_release_check_status(client, job_id, {"waiting"})
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

    release_waiting = wait_for_release_check_status(client, job_id, {"waiting"})
    pending = release_waiting["release_check_pending_choice"]
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

    completed = wait_for_release_check_status(client, job_id, {"completed"})
    assert received["search_choice"] == "search:Lastfm Artist Band"
    assert received["artist_choice"] == "artist-two"
    assert received["release_choice"] == "add"
    assert received["dry_run"] is True
    assert completed["release_check_checked_through"] == "2026-08-07"
    assert completed["release_check_resumed"] is True
    assert completed["release_check_results"][0]["release"] == "New Album Deluxe"
    assert client.get("/commands/check-new-releases-jobs").json() == []


def test_discography_web_job_collects_releases_and_confirms_removal(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

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

    def build(_spotify, playlist_ids, release_selector, **kwargs):
        received["playlist_ids"] = playlist_ids
        received["queue_3_playlist_id"] = kwargs["queue_3_playlist_id"]
        kwargs["progress_callback"]("Loading next discography artist")
        selected_ids = release_selector(artist, (studio, live))
        received["selected_ids"] = selected_ids
        selected = tuple(
            release for release in (studio, live) if release.spotify_id in selected_ids
        )
        selection = api.discography.ArtistSelection(
            spotify_id=artist.spotify_id,
            name=artist.name,
            source_queue=artist.queue,
            releases=selected,
            markers=(),
        )
        return api.discography.DiscographyPlan(
            start_queue="requeue",
            next_queue="memory_lane",
            artists=(selection,),
            total_releases=len(selected),
            open_slots=(-len(selected)) % 10,
        )

    def apply(_spotify, plan, **kwargs):
        received["applied_plan"] = plan
        kwargs["progress_callback"]("Removing confirmed artists")
        return api.discography.DiscographyRunSummary(
            removed_artists=1,
            removed_markers=2,
            next_queue="memory_lane",
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            discography_newfoundland_playlist="nf",
            discography_memory_lane_playlist="ml",
            discography_requeue_playlist="rq",
            the_queue_3_playlist="q3",
        ),
    )
    monkeypatch.setattr(api.discography, "build_discography_plan", build)
    monkeypatch.setattr(api.discography, "apply_discography_plan", apply)

    started = client.post(
        "/commands/plan-discographies",
        params={"dry_run": "false"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    waiting = wait_for_discography_status(client, job_id, {"waiting"})
    pending = waiting["discography_pending_choice"]
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

    submitted = client.post(
        f"/commands/plan-discographies-jobs/{job_id}/choice",
        json={"choice": "select", "release_ids": ["studio", "live"]},
    )
    assert submitted.status_code == 200

    confirmation = wait_for_discography_status(client, job_id, {"waiting"})
    assert confirmation["discography_pending_choice"]["kind"] == "confirm"
    assert confirmation["discography_total_releases"] == 2
    assert confirmation["discography_days"] == 1
    assert confirmation["discography_start_queue"] == "The Requeue"
    assert confirmation["discography_next_queue"] == "Memory Lane"
    assert confirmation["discography_results"][0]["release_names"] == [
        "Studio Album",
        "Live Album",
    ]

    confirmed = client.post(
        f"/commands/plan-discographies-jobs/{job_id}/choice",
        json={"choice": "apply"},
    )
    assert confirmed.status_code == 200
    completed = wait_for_discography_status(client, job_id, {"completed"})
    assert received["selected_ids"] == ("studio", "live")
    assert received["playlist_ids"] == {
        "newfoundland": "nf",
        "memory_lane": "ml",
        "requeue": "rq",
    }
    assert received["queue_3_playlist_id"] == "q3"
    assert received["applied_plan"].total_releases == 2
    assert completed["discography_removed_artists"] == 1
    assert completed["discography_removed_markers"] == 2
    assert client.get("/commands/plan-discographies-jobs").json() == []


def test_requeue_for_a_dream_web_job_reports_transition_and_reconnects(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    entered = Event()
    release_worker = Event()
    received: dict[str, object] = {}

    def run(spotify, playlist_id, **kwargs):
        received.update(
            spotify=spotify,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
        )
        kwargs["progress_callback"]("Loading Artist's discography")
        entered.set()
        assert release_worker.wait(2)
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            reqeueue_for_a_dream_playlist=("spotify:playlist:0000000000000000000000"),
        ),
    )
    monkeypatch.setattr(
        api.requeue_for_a_dream,
        "flush_requeue_for_a_dream",
        run,
    )

    started = client.post(
        "/commands/flush-requeue-for-a-dream",
        params={"dry_run": "true"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert entered.wait(2)
    assert [
        job["job_id"]
        for job in client.get("/commands/flush-requeue-for-a-dream-jobs").json()
    ] == [job_id]

    release_worker.set()
    completed = wait_for_requeue_for_a_dream_status(
        client,
        job_id,
        {"completed"},
    )
    assert received["playlist_id"] == "0000000000000000000000"
    assert received["dry_run"] is True
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


def test_palace_of_memory_web_job_reports_results_and_reconnects(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    entered = Event()
    release_worker = Event()
    received: dict[str, object] = {}

    def run(spotify, playlist_id, **kwargs):
        received.update(
            spotify=spotify,
            playlist_id=playlist_id,
            dry_run=kwargs["dry_run"],
            alphabetical_start=kwargs["alphabetical_start"],
        )
        kwargs["progress_callback"]("Refreshing saved albums at offset 50")
        entered.set()
        assert release_worker.wait(2)
        spotify_album = api.palace_of_memory.SpotifyAlbum(
            spotify_id="album-id",
            uri="spotify:album:album-id",
            artist="Palace Artist",
            album="Palace Album",
            saved=True,
            similarity=1.0,
        )
        first_track = api.palace_of_memory.SpotifyFirstTrack(
            spotify_id="track-id",
            uri="spotify:track:track-id",
            name="Opening Track",
        )
        return api.palace_of_memory.PalaceOfMemorySummary(
            generated_at=datetime(2026, 8, 4, 15, 30, tzinfo=UTC),
            playlist_id=playlist_id,
            dry_run=True,
            cutoff_date=date(2025, 12, 31),
            available_dates=5_092,
            alphabetical_start_index=5,
            alphabetical_next_index=10,
            alphabetical_cursor_overridden=True,
            playlist_length_before=7,
            playlist_length_after=8,
            album_refresh=api.palace_of_memory.SavedAlbumRefresh(
                checked_at=datetime(2026, 8, 4, tzinfo=UTC),
                previous=3_982,
                current=3_983,
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

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            palace_of_memory_playlist=("spotify:playlist:0000000000000000000000"),
        ),
    )
    monkeypatch.setattr(api.palace_of_memory, "fill_palace_of_memory", run)

    started = client.post(
        "/commands/fill-palace-of-memory",
        params={"dry_run": "true", "alphabetical_start": "6"},
    )

    assert started.status_code == 202
    job_id = started.json()["job_id"]
    assert entered.wait(2)
    assert [
        job["job_id"]
        for job in client.get("/commands/fill-palace-of-memory-jobs").json()
    ] == [job_id]

    release_worker.set()
    completed = wait_for_palace_of_memory_status(client, job_id, {"completed"})
    assert received["playlist_id"] == "0000000000000000000000"
    assert received["dry_run"] is True
    assert received["alphabetical_start"] == "6"
    assert completed["palace_alphabetical_start_index"] == 5
    assert completed["palace_alphabetical_next_index"] == 10
    assert completed["palace_alphabetical_cursor_overridden"] is True
    assert completed["palace_cutoff_date"] == "2025-12-31"
    assert completed["palace_available_dates"] == 5_092
    assert completed["palace_album_refresh"]["current"] == 3_983
    assert completed["palace_results"][0]["first_track"] == "Opening Track"
    assert completed["playlist_length_before"] == 7
    assert completed["playlist_length_after"] == 8
    assert any(
        entry["message"] == "Refreshing saved albums at offset 50"
        for entry in completed["logs"]
    )
    assert client.get("/commands/fill-palace-of-memory-jobs").json() == []


def test_palace_web_can_persist_only_cursor_without_playlist_config(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    def set_cursor(_spotify, position, **kwargs):
        kwargs["progress_callback"]("Refreshing the saved-album mirror")
        return api.palace_of_memory.AlphabeticalCursorUpdate(
            next_index=249,
            next_album=YourLibraryAlbum(
                artist="Cursor Artist",
                album="Cursor Album",
                uri="spotify:album:cursor-album",
            ),
            album_refresh=api.palace_of_memory.SavedAlbumRefresh(
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

    monkeypatch.setattr(api.palace_of_memory, "set_alphabetical_cursor", set_cursor)
    monkeypatch.setattr(
        api,
        "Settings",
        lambda: (_ for _ in ()).throw(
            AssertionError("cursor-only mode must not load playlist settings")
        ),
    )

    started = client.post(
        "/commands/fill-palace-of-memory",
        params={"dry_run": "false", "set_alphabetical_cursor": 250},
    )

    assert started.status_code == 202
    completed = wait_for_palace_of_memory_status(
        client,
        started.json()["job_id"],
        {"completed"},
    )
    assert completed["palace_cursor_only"] is True
    assert completed["palace_alphabetical_reference"] == "250"
    assert completed["palace_alphabetical_next_index"] == 249
    assert completed["palace_next_album_artist"] == "Cursor Artist"
    assert completed["palace_next_album"] == "Cursor Album"
    assert completed["playlist_length_before"] is None


def test_scrobble_history_web_job_reports_refresh_summary(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    history = tuple(
        api.blast_from_past.Scrobble(
            track="Track",
            artist="Artist",
            album="Album",
            timestamp_ms=index + 1,
        )
        for index in range(12)
    )
    received: dict[str, object] = {}

    def refresh(lastfm, **kwargs):
        received.update(lastfm=lastfm, **kwargs)
        kwargs["progress_callback"]("Fetching page 1 of 1 from Last.fm")
        return api.scrobble_history.ScrobbleHistorySummary(
            checked_at=datetime(2026, 8, 4, tzinfo=UTC),
            username="man-et-arms",
            history=history,
            export_scrobbles=10,
            legacy_scrobbles_added=1,
            live_scrobbles_added=1,
            dry_run=False,
            persisted=True,
            backup_path=Path("/tmp/scrobbles-backup.json.gz"),
        )

    monkeypatch.setattr(
        api,
        "Settings",
        lambda: SimpleNamespace(
            lastfm_api_key="lastfm-key",
            lastfm_username="man-et-arms",
        ),
    )
    monkeypatch.setattr(api.scrobble_history, "refresh_scrobble_history", refresh)

    started = client.post(
        "/commands/update-scrobble-history",
        params={"dry_run": "false"},
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
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    def complete_export(**kwargs):
        kwargs["progress_callback"]("albums", 2, 2, "Complete")
        return analysis_summary("async")

    monkeypatch.setattr(
        api.library_analysis,
        "analyse_library_async_routine",
        complete_export,
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
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    calls = []

    def complete_sync(spotify, **_kwargs):
        calls.append(spotify)
        spotify.event_callback(
            "Switching Spotify credentials to app5 and refreshing its token."
        )
        return analysis_summary("sync")

    monkeypatch.setattr(
        api.library_analysis,
        "analyse_library_sync_routine",
        complete_sync,
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
    client: TestClient,
    monkeypatch,
    full_rebuild: bool,
) -> None:
    from spotify_manager import api

    calls = []

    def complete_refresh(spotify, **kwargs):
        calls.append((spotify, kwargs["full_rebuild"]))
        kwargs["progress_callback"]("albums", 2, 2, "Complete")
        kwargs["progress_callback"]("tracks", 3, 3, "Complete")
        return analysis_summary("mirrors")

    monkeypatch.setattr(
        api.library_analysis,
        "refresh_live_library_mirrors_routine",
        complete_refresh,
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
    monkeypatch,
    resource: str,
    requested_full: bool,
    expected_full: bool,
) -> None:
    from spotify_manager import api

    calls = []

    def complete_resource(spotify, selected_resource, **kwargs):
        calls.append((spotify, selected_resource, kwargs["full_rebuild"]))
        kwargs["progress_callback"](selected_resource, 2, 2, "Complete")
        return api.library_analysis.LibrarySyncSummary(
            run_id="run-1",
            mode="mirrors",
            backup_dir="/tmp/mirrors/run-1",
            resources=(),
        )

    monkeypatch.setattr(
        api.library_analysis,
        "refresh_live_library_resource_routine",
        complete_resource,
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
    monkeypatch,
    http_status: int | None,
    failure: str,
) -> None:
    from spotify_manager import api

    def wait_for_server(_spotify, **kwargs):
        keep_waiting = kwargs["retry_wait"](
            api.library_analysis.RetryNotice(
                http_status=http_status,
                operation="reading artists",
                attempt=1,
                delay_seconds=60,
            )
        )
        if not keep_waiting:
            raise api.library_analysis.LibraryAnalysisCancelledError("Paused")
        return analysis_summary("sync")

    monkeypatch.setattr(
        api.library_analysis,
        "analyse_library_sync_routine",
        wait_for_server,
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
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    release = api.Event()

    def blocked_export(**kwargs):
        kwargs["echo"]("Still reading exported albums.")
        release.wait(2)
        return analysis_summary("async")

    monkeypatch.setattr(
        api.library_analysis,
        "analyse_library_async_routine",
        blocked_export,
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
