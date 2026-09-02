"""Failure-state contracts shared by reconnectable API background jobs."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

from spotify_manager import api


class CallbackSpotify:
    """Spotify stand-in recording temporary event callback installation."""

    def __init__(self) -> None:
        self.callback = None

    def set_event_callback(self, callback):
        previous = self.callback
        self.callback = callback
        return previous


class ImmediateEvent:
    """Event stand-in that records waits without delaying the test suite."""

    def __init__(self, *, cancel_on_wait: bool = False) -> None:
        self.cancel_on_wait = cancel_on_wait
        self.waits: list[float] = []
        self.set_value = False

    def is_set(self) -> bool:
        return self.set_value

    def set(self) -> None:
        self.set_value = True

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(0 if timeout is None else timeout)
        if self.cancel_on_wait:
            self.set_value = True
        return self.set_value


@dataclass(frozen=True)
class RunnerSpec:
    """Everything needed to execute one job runner up to its routine call."""

    name: str
    command: str
    run: Callable[[str, object], None]
    module: ModuleType
    target: str
    domain_error: Callable[[], Exception]
    cancellation_error: type[Exception] | None = None
    rate_limited: bool = False


RUNNERS = (
    RunnerSpec(
        "blast",
        "blast_from_the_past",
        lambda job_id, spotify: api._run_blast_job(
            job_id,
            spotify,
            "playlist",
            1,
            None,
            False,  # type: ignore[arg-type]
        ),
        api.blast_from_past,
        "add_blast_from_past_to_spotify",
        lambda: api.blast_from_past.BlastFromPastError("blast failed"),
        api.blast_from_past.BlastFromPastCancelledError,
        True,
    ),
    RunnerSpec(
        "blast-artists",
        "blast_from_the_past_artists",
        lambda job_id, spotify: api._run_blast_artist_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            "playlist",
            5,
            False,
        ),
        api.blast_from_past_artists,
        "add_dormant_artists_to_blast_from_past",
        lambda: api.blast_from_past_artists.BlastFromPastArtistsError(
            "dormant artists failed"
        ),
        api.blast_from_past.BlastFromPastCancelledError,
        True,
    ),
    RunnerSpec(
        "daily",
        "daily_mind_radio",
        lambda job_id, spotify: api._run_daily_mind_radio_job(
            job_id,
            spotify,
            "playlist",
            False,  # type: ignore[arg-type]
        ),
        api.daily_mind_radio,
        "add_daily_mind_radio_to_spotify",
        lambda: api.blast_from_past.BlastFromPastError("daily failed"),
        api.blast_from_past.BlastFromPastCancelledError,
        True,
    ),
    RunnerSpec(
        "found-art",
        "found_art",
        lambda job_id, spotify: api._run_found_art_job(
            job_id,
            spotify,
            "playlist",
            "key",
            "user",
            1,  # type: ignore[arg-type]
        ),
        api.found_art,
        "run_found_art",
        lambda: api.found_art.FoundArtError("found art failed"),
    ),
    RunnerSpec(
        "sauvignon",
        "fill_sauvignon_from_lastfm",
        lambda job_id, spotify: api._run_sauvignon_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            "playlist",
            "key",
            "user",
            None,
            20,
            30,
            True,
        ),
        api.sauvignon,
        "fill_sauvignon_from_lastfm",
        lambda: api.sauvignon.SauvignonError("sauvignon failed"),
        api._SauvignonJobCancelledError,
        True,
    ),
    RunnerSpec(
        "queue-fill",
        "fill_queue_from_lastfm",
        lambda job_id, spotify: api._run_queue_fill_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            api.the_queue.QueuePlaylists("queue", "queue2", "new", "queue3", "unlucky"),
            "key",
            "user",
            1,
            None,
            30,
            True,
        ),
        api.the_queue,
        "fill_queue_from_lastfm",
        lambda: api.the_queue.QueueError("queue fill failed"),
        api._QueueJobCancelledError,
        True,
    ),
    RunnerSpec(
        "queue-flush",
        "flush_queue",
        lambda job_id, spotify: api._run_queue_flush_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            api.the_queue.QueuePlaylists("queue", "queue2", "new", "queue3", "unlucky"),
            True,
        ),
        api.the_queue,
        "flush_queue",
        lambda: api.the_queue.QueueError("queue flush failed"),
        api._QueueJobCancelledError,
        True,
    ),
    RunnerSpec(
        "new-kids",
        "flush_new_kids",
        lambda job_id, spotify: api._run_new_kids_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            "new",
            "queue",
            "great",
            "unlucky",
            "newfoundland",
            True,
        ),
        api.new_kids,
        "flush_new_kids",
        lambda: api.new_kids.NewKidsError("new kids failed"),
        api._NewKidsJobCancelledError,
        True,
    ),
    RunnerSpec(
        "queue-3",
        "flush_queue_3",
        lambda job_id, spotify: api._run_queue_3_job(
            job_id,
            spotify,
            "playlist",
            True,  # type: ignore[arg-type]
        ),
        api.queue_3,
        "flush_queue_3",
        lambda: api.queue_3.Queue3Error("queue 3 failed"),
        api._Queue3JobCancelledError,
        True,
    ),
    RunnerSpec(
        "new-wine",
        "flush_new_wine",
        lambda job_id, spotify: api._run_new_wine_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            "new",
            "sauvignon",
            "cellar",
            True,
            False,
        ),
        api.new_wine,
        "flush_new_wine",
        lambda: api.new_wine.NewWineError("new wine failed"),
        api._NewWineJobCancelledError,
        True,
    ),
    RunnerSpec(
        "slow-listening",
        "flush_slow_listening",
        lambda job_id, spotify: api._run_slow_listening_job(
            job_id,
            spotify,
            "playlist",
            True,  # type: ignore[arg-type]
        ),
        api.slow_listening,
        "flush_slow_listening",
        lambda: api.slow_listening.SlowListeningError("slow failed"),
        api._SlowListeningJobCancelledError,
        True,
    ),
    RunnerSpec(
        "something-old",
        "something_old",
        lambda job_id, spotify: api._run_something_old_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            "playlist",
            "key",
            "user",
            True,
        ),
        api.something_old,
        "run_something_old",
        lambda: api.something_old.SomethingOldError("something old failed"),
        api._SomethingOldJobCancelledError,
        True,
    ),
    RunnerSpec(
        "release-check",
        "check_new_releases",
        lambda job_id, spotify: api._run_release_check_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            "key",
            "user",
            True,
        ),
        api.release_check,
        "run_release_check",
        lambda: api.release_check.ReleaseCheckError("release check failed"),
        api._ReleaseCheckJobCancelledError,
        True,
    ),
    RunnerSpec(
        "discography",
        "plan_discographies",
        lambda job_id, spotify: api._run_discography_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            {},
            "queue3",
            True,
        ),
        api.discography,
        "build_discography_plan",
        lambda: api.discography.DiscographyError("discography failed"),
        api._DiscographyJobCancelledError,
        True,
    ),
    RunnerSpec(
        "requeue",
        "flush_requeue_for_a_dream",
        lambda job_id, spotify: api._run_requeue_for_a_dream_job(
            job_id,
            spotify,
            "playlist",
            True,  # type: ignore[arg-type]
        ),
        api.requeue_for_a_dream,
        "flush_requeue_for_a_dream",
        lambda: api.requeue_for_a_dream.RequeueForADreamError("requeue failed"),
        api._RequeueForADreamJobCancelledError,
        True,
    ),
    RunnerSpec(
        "palace",
        "fill_palace_of_memory",
        lambda job_id, spotify: api._run_palace_of_memory_job(
            job_id,
            spotify,  # type: ignore[arg-type]
            "playlist",
            True,
            None,
            None,
        ),
        api.palace_of_memory,
        "fill_palace_of_memory",
        lambda: api.palace_of_memory.PalaceOfMemoryError("palace failed"),
        api._PalaceOfMemoryJobCancelledError,
        True,
    ),
    RunnerSpec(
        "scrobble-history",
        "update_scrobble_history",
        lambda job_id, _spotify: api._run_scrobble_history_job(
            job_id, "key", "user", True
        ),
        api.scrobble_history,
        "refresh_scrobble_history",
        lambda: api.scrobble_history.ScrobbleHistoryError("history failed"),
    ),
)


def _success_result(spec: RunnerSpec) -> object:
    """Build the smallest valid routine result for each worker contract."""
    now = datetime.now(UTC)
    if spec.name == "blast":
        return SimpleNamespace(
            requested_count=1,
            playlist_length_before=0,
            playlist_length_after=0,
            added=0,
            batch=None,
            results=(),
        )
    if spec.name == "blast-artists":
        return api.blast_from_past_artists.DormantArtistSummary(
            current_year=2026,
            history_years=(2022, 2023, 2024, 2025),
            candidate_count=0,
            represented_count=0,
            playlist_length_before=0,
            playlist_length_after=0,
            requested_count=5,
            results=(),
        )
    if spec.name == "daily":
        return SimpleNamespace(
            batch=SimpleNamespace(
                selections=(),
                target_dates=(),
                missing_dates=(),
                generated_at=None,
            ),
            playlist_length_before=None,
            playlist_length_after=None,
            added=0,
            results=(),
        )
    if spec.name == "found-art":
        return SimpleNamespace(
            requested_count=1,
            playlist_length_before=0,
            playlist_length_after=0,
            added=0,
            week_start=date(2026, 8, 10),
            history_tracks=10,
            history_scrobbles=20,
            live_scrobbles_added=1,
            candidate_count=5,
            results=(),
        )
    if spec.name == "sauvignon":
        return api.sauvignon.SauvignonSummary(
            generated_at=now,
            week_start=date(2026, 8, 7),
            playlist_id="playlist",
            requested_count=1,
            history_albums=10,
            history_scrobbles=20,
            live_scrobbles_added=1,
            seed_count=3,
            track_candidate_count=5,
            album_candidate_count=2,
            playlist_length_before=0,
            playlist_length_after=0,
            paused=False,
            dry_run=True,
            results=(),
        )
    if spec.name == "queue-fill":
        return api.the_queue.FillSummary(
            week_start=date(2026, 8, 7),
            requested_count=1,
            history_artists=10,
            history_scrobbles=20,
            live_scrobbles_added=1,
            seed_count=3,
            candidate_count=5,
            playlist_length_before=0,
            playlist_length_after=0,
            paused=False,
            dry_run=True,
            results=(),
        )
    if spec.name == "queue-flush":
        return api.the_queue.FlushSummary(
            run_id="run",
            playlist_length_before=0,
            playlist_length_after=0,
            total=0,
            processed=0,
            resumed=False,
            dry_run=True,
            results=(),
        )
    if spec.name == "new-kids":
        return api.new_kids.FlushSummary(
            results=(),
            prefill=(),
            postfill=(),
            playlist_length_before=2,
            playlist_length_after=2,
            paused=False,
            resumed=False,
            dry_run=True,
        )
    if spec.name == "queue-3":
        return api.queue_3.FlushSummary(
            run_id="run",
            total=0,
            processed=0,
            advanced=0,
            changed_releases=0,
            completed_artists=0,
            skipped=0,
            annual_import=(),
            paused=False,
            dry_run=True,
            resumed=False,
            results=(),
        )
    if spec.name == "new-wine":
        return api.new_wine.FlushSummary(
            run_id="run",
            total=0,
            processed=0,
            advanced=0,
            dropped=0,
            sent_to_sauvignon=0,
            completed_singles=0,
            skipped=0,
            albums_unsaved=0,
            paused=False,
            dry_run=True,
            resumed=False,
            results=(),
        )
    if spec.name == "slow-listening":
        return api.slow_listening.FlushSummary(
            run_id="run",
            total=0,
            processed=0,
            advanced=0,
            completed_artists=0,
            skipped=0,
            paused=False,
            dry_run=True,
            resumed=False,
            results=(),
        )
    if spec.name == "something-old":
        return api.something_old.SomethingOldSummary(
            generated_at=now,
            playlist_id="playlist",
            playlist_length_before=0,
            playlist_length_after=0,
            dry_run=True,
            action="cancelled",
            history_refresh=None,
            ranking_preview=(),
            artist=None,
            spotify_artist=None,
            mode=None,
            release=None,
            tracks=(),
        )
    if spec.name == "release-check":
        return api.release_check.ReleaseCheckSummary(
            run_id="run",
            checked_from=date(2026, 1, 1),
            checked_through=date(2026, 8, 11),
            artists_total=0,
            artists_processed=0,
            dry_run=True,
            resumed=False,
            paused=False,
            history_refresh=None,
            results=(),
        )
    if spec.name == "discography":
        return api.discography.DiscographyPlan(
            start_queue="newfoundland",
            next_queue="memory_lane",
            artists=(),
            total_releases=0,
            open_slots=10,
        )
    if spec.name == "requeue":
        return api.requeue_for_a_dream.RequeueForADreamSummary(
            recorded_at=now,
            playlist_id="playlist",
            dry_run=True,
            action="empty",
            playlist_length_before=0,
            playlist_length_after=0,
        )
    if spec.name == "palace":
        return api.palace_of_memory.PalaceOfMemorySummary(
            generated_at=now,
            playlist_id="playlist",
            dry_run=True,
            cutoff_date=date(2025, 12, 31),
            available_dates=0,
            alphabetical_start_index=0,
            alphabetical_next_index=0,
            alphabetical_cursor_overridden=False,
            playlist_length_before=0,
            playlist_length_after=0,
            album_refresh=api.palace_of_memory.SavedAlbumRefresh(
                checked_at=now,
                previous=0,
                current=0,
                added=0,
                removed=0,
                skipped=0,
                persisted=False,
                backup_path=None,
            ),
            results=(),
        )
    if spec.name == "scrobble-history":
        return api.scrobble_history.ScrobbleHistorySummary(
            checked_at=now,
            username="user",
            history=(),
            export_scrobbles=10,
            legacy_scrobbles_added=0,
            live_scrobbles_added=1,
            dry_run=True,
            persisted=False,
            backup_path=Path("history.backup.json"),
        )
    raise AssertionError(f"No success result for {spec.name}")


def _job(spec: RunnerSpec) -> api._BlastJob:
    job = api._BlastJob(
        result=api.BlastJobResult(
            job_id=f"job-{spec.name}",
            command=spec.command,
        )
    )
    with api._blast_jobs_lock:
        api._blast_jobs[job.result.job_id] = job
    return job


def _remove_job(job: api._BlastJob) -> None:
    with api._blast_jobs_lock:
        api._blast_jobs.pop(job.result.job_id, None)


@pytest.mark.parametrize("spec", RUNNERS, ids=lambda spec: spec.name)
@pytest.mark.parametrize("failure_kind", ["domain", "unexpected"])
def test_job_runners_capture_failures(
    monkeypatch: pytest.MonkeyPatch,
    spec: RunnerSpec,
    failure_kind: str,
) -> None:
    job = _job(spec)
    spotify = CallbackSpotify()
    error = spec.domain_error() if failure_kind == "domain" else RuntimeError("boom")

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(spec.module, spec.target, fail)
    try:
        spec.run(job.result.job_id, spotify)
    finally:
        _remove_job(job)

    assert job.result.status == "failed"
    assert job.result.completed_at is not None
    assert job.result.logs
    assert spotify.callback is None
    if failure_kind == "unexpected":
        assert "Unexpected" in str(job.result.detail)


@pytest.mark.parametrize("spec", RUNNERS, ids=lambda spec: spec.name)
def test_job_runners_serialize_success_and_restore_callbacks(
    monkeypatch: pytest.MonkeyPatch,
    spec: RunnerSpec,
) -> None:
    job = _job(spec)
    spotify = CallbackSpotify()
    summary = _success_result(spec)
    monkeypatch.setattr(spec.module, spec.target, lambda *_args, **_kwargs: summary)

    try:
        spec.run(job.result.job_id, spotify)
    finally:
        _remove_job(job)

    assert job.result.status in {"completed", "cancelled"}
    assert job.result.completed_at is not None
    assert job.result.logs
    assert spotify.callback is None


@pytest.mark.parametrize(
    "spec",
    tuple(spec for spec in RUNNERS if spec.rate_limited),
    ids=lambda spec: spec.name,
)
@pytest.mark.parametrize("failure_kind", ["rate", "transient"])
def test_interactive_job_runners_pause_for_retryable_spotify_failures(
    monkeypatch: pytest.MonkeyPatch,
    spec: RunnerSpec,
    failure_kind: str,
) -> None:
    job = _job(spec)
    spotify = CallbackSpotify()
    error: Exception
    if failure_kind == "rate":
        error = api.review_album_limits.SpotifyRateLimitError(120)
    else:
        error = api.review_album_limits.SpotifyTransientServerError(
            502,
            "loading playlist",
            3,
        )

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(spec.module, spec.target, fail)
    try:
        spec.run(job.result.job_id, spotify)
    finally:
        _remove_job(job)

    assert job.result.status == "paused"
    assert job.result.completed_at is not None
    assert job.result.logs
    if failure_kind == "rate":
        assert job.result.retry_at is not None


def test_new_wine_retries_rate_limited_operation_automatically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Retry-After response resumes the same New Wine API operation."""
    spec = next(spec for spec in RUNNERS if spec.name == "new-wine")
    job = _job(spec)
    cancel_event = ImmediateEvent()
    job.cancel_event = cancel_event  # type: ignore[assignment]
    attempts = 0

    def flush(*_args, retry_call, **_kwargs):
        def operation() -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise api.SpotifyException(
                    429,
                    -1,
                    "rate limited",
                    headers={"Retry-After": "1"},
                )
            return object()

        retry_call(operation, "refilling New Wine from Wine Cellar")
        return _success_result(spec)

    monkeypatch.setattr(api.new_wine, "flush_new_wine", flush)
    try:
        spec.run(job.result.job_id, CallbackSpotify())
    finally:
        _remove_job(job)

    assert attempts == 2
    assert cancel_event.waits == [1]
    assert job.result.status == "completed"
    assert job.result.retry_at is None
    assert any("Retrying automatically" in entry.message for entry in job.result.logs)


def test_new_wine_rate_limit_wait_can_be_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel interrupts an automatic Retry-After wait without another call."""
    spec = next(spec for spec in RUNNERS if spec.name == "new-wine")
    job = _job(spec)
    cancel_event = ImmediateEvent(cancel_on_wait=True)
    job.cancel_event = cancel_event  # type: ignore[assignment]
    attempts = 0

    def flush(*_args, retry_call, **_kwargs):
        def operation() -> object:
            nonlocal attempts
            attempts += 1
            raise api.SpotifyException(
                429,
                -1,
                "rate limited",
                headers={"Retry-After": "30"},
            )

        retry_call(operation, "refilling New Wine from Wine Cellar")
        return _success_result(spec)

    monkeypatch.setattr(api.new_wine, "flush_new_wine", flush)
    try:
        spec.run(job.result.job_id, CallbackSpotify())
    finally:
        _remove_job(job)

    assert attempts == 1
    assert cancel_event.waits == [30]
    assert job.result.status == "cancelled"
    assert job.result.retry_at is None


@pytest.mark.parametrize(
    "spec",
    tuple(
        spec
        for spec in RUNNERS
        if spec.name
        in {
            "blast-artists",
            "sauvignon",
            "queue-fill",
            "queue-flush",
        }
    ),
    ids=lambda spec: spec.name,
)
def test_queue_jobs_report_connection_failures(
    monkeypatch: pytest.MonkeyPatch,
    spec: RunnerSpec,
) -> None:
    job = _job(spec)
    spotify = CallbackSpotify()

    def fail(*_args, **_kwargs):
        raise api.RequestException("offline")

    monkeypatch.setattr(spec.module, spec.target, fail)
    try:
        spec.run(job.result.job_id, spotify)
    finally:
        _remove_job(job)

    assert job.result.status == "failed"
    assert job.result.detail == api.SPOTIFY_CONNECTION_FAILURE_DETAIL
    assert job.result.completed_at is not None


@pytest.mark.parametrize(
    "spec",
    tuple(spec for spec in RUNNERS if spec.cancellation_error is not None),
    ids=lambda spec: spec.name,
)
def test_interactive_job_runners_record_clean_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    spec: RunnerSpec,
) -> None:
    job = _job(spec)
    spotify = CallbackSpotify()
    assert spec.cancellation_error is not None

    def cancel(*_args, **_kwargs):
        raise spec.cancellation_error

    monkeypatch.setattr(spec.module, spec.target, cancel)
    try:
        spec.run(job.result.job_id, spotify)
    finally:
        _remove_job(job)

    assert job.result.status == "cancelled"
    assert job.result.completed_at is not None
    assert job.result.logs
