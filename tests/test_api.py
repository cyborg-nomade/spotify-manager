"""Tests for the FastAPI interface.

Both the Spotify client and the library are overridden so no network,
credentials, or YourLibrary.json file are needed.
"""

from datetime import UTC
from datetime import date
from datetime import datetime
from time import monotonic
from time import sleep
from types import SimpleNamespace

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

    def __init__(self) -> None:
        self.event_callback = None

    def set_event_callback(self, callback):
        previous = self.event_callback
        self.event_callback = callback
        return previous

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
    with api._blast_jobs_lock:
        api._blast_jobs.clear()
    app.dependency_overrides[get_client] = lambda: FakeSpotify()
    app.dependency_overrides[get_analysis_client] = lambda: FakeSpotify()
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


def test_auth_check(client: TestClient) -> None:
    assert client.get("/auth/check").json() == {"status": "ok"}


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
    assert any("Waiting until" in entry["message"] for entry in waiting["logs"])

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
