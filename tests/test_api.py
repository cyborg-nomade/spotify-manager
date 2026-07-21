"""Tests for the FastAPI interface.

Both the Spotify client and the library are overridden so no network,
credentials, or YourLibrary.json file are needed.
"""

from time import monotonic
from time import sleep

import pytest
from fastapi.testclient import TestClient

from spotify_manager.api import app
from spotify_manager.api import get_analysis_client
from spotify_manager.api import get_client
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
    """Minimal spotipy stand-in: only album_tracks is exercised."""

    def album_tracks(self, album_id, limit=50, offset=0):
        return {
            "items": [
                {"id": "t1", "name": "Airbag", "uri": "spotify:track:t1"},
                {"id": "t2", "name": "Karma Police", "uri": "spotify:track:t2"},
                {"id": "t3", "name": "Let Down", "uri": "spotify:track:t3"},
            ],
            "next": None,
        }


@pytest.fixture
def client() -> TestClient:
    from spotify_manager import api

    with api._analysis_jobs_lock:
        api._analysis_jobs.clear()
    app.dependency_overrides[get_client] = lambda: FakeSpotify()
    app.dependency_overrides[get_analysis_client] = lambda: FakeSpotify()
    app.dependency_overrides[get_library] = _library
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    with api._analysis_jobs_lock:
        api._analysis_jobs.clear()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_artist_stats_endpoint(client: TestClient) -> None:
    resp = client.get("/artists/stats", params={"name": "radiohead"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["artist_id"] == "art1"
    assert body["liked_tracks"] == 2
    assert body["saved_releases"] == 1
    assert body["source"] == "files"


def test_artist_stats_requires_an_argument(client: TestClient) -> None:
    assert client.get("/artists/stats").status_code == 400


def test_album_evaluation_endpoint(client: TestClient) -> None:
    resp = client.get("/albums/evaluation", params={"name": "OK Computer"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["album_id"] == "alb1"
    assert body["decision"] == "keep"  # 2/3 liked
    assert body["total_tracks"] == 3
    assert body["liked_tracks"] == 2


def test_album_evaluation_not_found(client: TestClient) -> None:
    resp = client.get("/albums/evaluation", params={"name": "Nope"})
    assert resp.status_code == 404


def test_count_artists_endpoint(client: TestClient, monkeypatch) -> None:
    from spotify_manager import api

    monkeypatch.setattr(api, "count_artists_in_library", lambda: 42)
    resp = client.get("/commands/count-artists")
    assert resp.json() == {"count": 42}


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


def test_live_analysis_job_can_be_cancelled_during_retry_wait(
    client: TestClient,
    monkeypatch,
) -> None:
    from spotify_manager import api

    def wait_for_server(_spotify, **kwargs):
        keep_waiting = kwargs["retry_wait"](
            api.library_analysis.RetryNotice(
                http_status=502,
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

    cancelled = client.post(f"/commands/library-analysis-jobs/{job_id}/cancel")

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelling"
    result = wait_for_job_status(client, job_id, {"cancelled"})
    assert "Progress was saved" in result["detail"]


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
