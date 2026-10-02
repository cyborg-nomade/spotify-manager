"""Observe each explicit analysis callback, channel and presentation boundary."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from threading import Event
from threading import Lock
from typing import cast

import pytest
from spotipy import Spotify

from spotify_manager.interfaces.http.analysis_worker import AnalysisWorker
from spotify_manager.interfaces.http.analysis_worker import EventCallback
from spotify_manager.interfaces.http.analysis_worker import spotify_event_setter
from spotify_manager.interfaces.http.job_records import AnalysisJob
from spotify_manager.interfaces.http.models.analysis import AnalysisJobResult
from spotify_manager.interfaces.http.models.analysis import AnalysisResourceProgress
from spotify_manager.interfaces.http.models.common import JobStatus
from spotify_manager.routines import analyse_library as analysis


@dataclass
class LogRecorder:
    """Require callers to hold their original registry lock for accepted messages.

    Args:
        lock: Original registry synchronization authority.
        calls: Observed job/message pairs without a second production log buffer.
    """

    lock: Lock
    calls: list[tuple[AnalysisJob, str]] = field(default_factory=list)

    def __call__(self, job: AnalysisJob, message: str) -> None:
        """Observe one sink call under the owner's lock.

        Args:
            job: Exact callback owner.
            message: Unmodified routine event text.
        """
        assert self.lock.locked()
        self.calls.append((job, message))


def _now() -> datetime:
    return datetime(2026, 9, 24, tzinfo=UTC)


def _worker(identifier: str = "analysis", lock: Lock | None = None) -> AnalysisWorker:
    registry_lock = Lock() if lock is None else lock
    result = AnalysisJobResult(
        job_id=identifier,
        command="analyse_library_async",
        resources={
            "albums": AnalysisResourceProgress(),
            "tracks": AnalysisResourceProgress(),
            "artists": AnalysisResourceProgress(),
        },
    )
    return AnalysisWorker(
        AnalysisJob(result, Event()),
        registry_lock,
        _now,
        LogRecorder(registry_lock),
        "async",
        None,
        False,
        None,
    )


def _messages(worker: AnalysisWorker) -> list[str]:
    assert isinstance(worker.append, LogRecorder)
    return [message for _, message in worker.append.calls]


def _summary() -> analysis.LibrarySyncSummary:
    return analysis.LibrarySyncSummary(
        "run-1",
        "async",
        "/backup",
        (
            analysis.ResourceSyncSummary("albums", "export", 1, 2, 1, 0),
            analysis.ResourceSyncSummary("tracks", "export", 5, 3, 0, 2, 1),
        ),
    )


def test_start_and_finish_use_original_clock_and_log_order() -> None:
    """Keep startup presentation separate from terminal timestamp recording."""
    worker = _worker()
    worker.start()
    assert worker.job.result.status == "running"
    assert worker.job.result.started_at == "2026-09-24T00:00:00+00:00"
    assert worker.job.result.completed_at is None
    assert _messages(worker) == ["Async analysis started."]
    worker.finish()
    assert worker.job.result.completed_at == "2026-09-24T00:00:00+00:00"


@pytest.mark.parametrize(("total", "count"), [(None, "3"), (2, "3 / 3"), (5, "3 / 5")])
def test_progress_preserves_original_count_and_status_text(
    total: int | None, count: str
) -> None:
    """Retain unknown totals and totals smaller than the accepted count.

    Args:
        total: Original optional observed total.
        count: Original rendered count at this boundary.
    """
    worker = _worker()
    worker.progress("tracks", 3, total, "Read")
    assert worker.job.result.status == "running"
    assert worker.job.result.detail == "Tracks: Read"
    assert worker.job.result.resources["tracks"].completed == 3
    assert worker.job.result.resources["tracks"].total == total
    assert _messages(worker) == [f"Tracks: Read ({count})."]
    worker.progress("tracks", 4, total, "Read")
    assert len(_messages(worker)) == 1
    assert worker.job.result.resources["tracks"].completed == 4


def test_progress_preserves_cancellation_detail() -> None:
    """Update resource observations without replacing a cancellation request."""
    worker = _worker()
    worker.job.result.status = "cancelling"
    worker.job.result.detail = "Stopping"
    worker.progress("albums", 1, None, "Read")
    assert worker.job.result.status == "cancelling"
    assert worker.job.result.detail == "Stopping"
    assert _messages(worker) == ["Albums: Read (1)."]


def test_missing_progress_bucket_keeps_original_key_error() -> None:
    """Do not silently add resources absent from the original job view."""
    worker = _worker()
    del worker.job.result.resources["artists"]
    with pytest.raises(KeyError, match="artists"):
        worker.progress("artists", 0, None, "Read")
    assert worker.job.result.status == "queued"
    assert _messages(worker) == []


@pytest.mark.parametrize("protected", ["waiting", "cancelling"])
def test_echo_protects_waiting_or_cancel_detail(protected: JobStatus) -> None:
    """Accept callback messages without erasing the original stopping context.

    Args:
        protected: Original protected phase under observation.
    """
    worker = _worker()
    worker.job.result.status = protected
    worker.job.result.detail = "Protected"
    worker.echo("Observed event")
    assert worker.job.result.detail == "Protected"
    assert _messages(worker) == ["Observed event"]


def test_echo_keeps_original_empty_detail_behavior() -> None:
    """Forward empty messages and still replace unprotected detail as before."""
    worker = _worker()
    worker.echo("")
    assert worker.job.result.detail == ""
    assert _messages(worker) == [""]


@pytest.mark.parametrize("http_status", [None, 500])
@pytest.mark.parametrize("cancelled", [False, True])
def test_retry_wait_owns_its_signal_and_original_resume(
    http_status: int | None, cancelled: bool
) -> None:
    """Preserve zero-delay retry text, signal interpretation and resumed detail.

    Args:
        http_status: Transport interruption or original HTTP failure.
        cancelled: Whether this worker's signal is already set.
    """
    worker = _worker()
    if cancelled:
        worker.job.cancel_event.set()
    notice = analysis.RetryNotice(http_status, "loading tracks", 2, 0)
    failure = (
        "Spotify connection interrupted" if http_status is None else "Spotify HTTP 500"
    )
    assert worker.retry_wait(notice) is not cancelled
    assert worker.job.result.retry_at is None
    assert _messages(worker)[0] == (
        "Waiting until 2026-09-24T00:00:00+00:00 before retry "
        f"2 after {failure} while loading tracks. Cancel to save and stop."
    )
    if cancelled:
        assert worker.job.result.status == "waiting"
        assert len(_messages(worker)) == 1
        return
    assert worker.job.result.status == "running"
    assert _messages(worker)[1] == "Retrying Spotify request now."


@dataclass
class RoutineProbe:
    """Record explicit routine dispatch without Spotify or filesystem effects.

    Args:
        arguments: Accepted positional dispatch arguments.
        options: Accepted callbacks and original routine options.
    """

    arguments: tuple[object, ...] = ()
    options: dict[str, object] = field(default_factory=dict)

    def __call__(
        self, *arguments: object, **options: object
    ) -> analysis.LibrarySyncSummary:
        """Accept the exact routine call and return a fixed typed summary.

        Args:
            arguments: Original supplied SDK and resource arguments.
            options: Original keyword callbacks and refresh flags.

        Returns:
            A fixed accepted summary without external work.
        """
        self.arguments = arguments
        self.options = options
        return _summary()


@pytest.mark.parametrize(
    ("mode", "resource", "routine"),
    [
        ("async", None, "analyse_library_async_routine"),
        ("sync", None, "analyse_library_sync_routine"),
        ("mirrors", None, "refresh_live_library_mirrors_routine"),
        ("mirrors", "albums", "refresh_live_library_resource_routine"),
    ],
)
def test_dispatch_uses_exact_routine_and_owned_callbacks(
    mode: analysis.AnalysisMode,
    resource: analysis.ResourceName | None,
    routine: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve every dispatch mode, original flags and callback identity.

    Args:
        mode: Original mode selection.
        resource: Optional original single-resource mirror selection.
        routine: Original facade routine to observe.
        monkeypatch: Scoped routine replacement with no external effects.
    """
    worker = _worker()
    worker.mode, worker.mirror_resource = mode, resource
    worker.spotify = cast(Spotify, object())
    worker.full_rebuild = True
    probe = RoutineProbe()
    monkeypatch.setattr(analysis, routine, probe)
    assert worker.execute() == _summary()
    assert probe.options["echo"] == worker.echo
    assert probe.options["progress_callback"] == worker.progress
    assert probe.options["cancel_check"] == worker.job.cancel_event.is_set
    if mode == "async":
        assert probe.arguments == ()
        assert "retry_wait" not in probe.options
        return
    assert probe.arguments[0] is worker.spotify
    assert probe.options["retry_wait"] == worker.retry_wait
    if mode == "mirrors":
        assert probe.options["full_rebuild"] is True


@pytest.mark.parametrize("mode", ["sync", "mirrors"])
def test_live_dispatch_requires_original_client(mode: analysis.AnalysisMode) -> None:
    """Reject missing live clients with the original operation-specific message.

    Args:
        mode: Original live analysis or mirror operation.
    """
    worker = _worker()
    worker.mode = mode
    operation = "live analysis" if mode == "sync" else "live mirror refresh"
    with pytest.raises(analysis.LibrarySyncError) as error:
        worker.execute()
    assert str(error.value) == f"A Spotify client is required for {operation}."


@pytest.mark.parametrize("delay", [None, 0, 60])
def test_pause_keeps_original_optional_timestamp(delay: int | None) -> None:
    """Retain absent and zero retry delays without normalizing their meaning.

    Args:
        delay: Original rate-limit header interpretation.
    """
    worker = _worker()
    worker.paused(analysis.SpotifyRateLimitError(delay))
    assert worker.job.result.status == "paused"
    expected = None if delay is None else f"2026-09-24T00:{delay // 60:02d}:00+00:00"
    assert worker.job.result.retry_at == expected
    assert _messages(worker) == ["Spotify rate limit reached. Progress was saved."]


def test_cancellation_keeps_original_saved_progress_message() -> None:
    """Keep clean cancellation and its accepted saved-progress explanation."""
    worker = _worker()
    worker.cancelled(analysis.LibraryAnalysisCancelledError("Stopped."))
    assert worker.job.result.status == "cancelled"
    assert worker.job.result.detail == "Stopped. Progress was saved."
    assert _messages(worker) == ["Stopped. Progress was saved."]


def test_failure_keeps_original_distinct_detail_and_log() -> None:
    """Keep the anticipated failure detail and its original log prefix."""
    worker = _worker()
    worker.failed(analysis.LibrarySyncError("Invalid source"))
    assert worker.job.result.status == "failed"
    assert worker.job.result.detail == "Invalid source"
    assert _messages(worker) == ["Analysis failed: Invalid source"]


def test_unexpected_failure_keeps_original_outer_boundary_message() -> None:
    """Present errors classified by the unchanged outer compatibility boundary."""
    worker = _worker()
    worker.unexpected_failure(ValueError("Unexpected source"))
    assert worker.job.result.status == "failed"
    assert worker.job.result.detail == "Unexpected analysis error: Unexpected source"
    assert _messages(worker) == ["Unexpected analysis error: Unexpected source"]


def test_success_keeps_resource_order_and_final_summary() -> None:
    """Preserve accepted run identity, backup path and original ordered diff logs."""
    worker = _worker()
    worker.completed(_summary())
    assert worker.job.result.status == "completed"
    assert worker.job.result.run_id == "run-1"
    assert worker.job.result.backup_dir == "/backup"
    assert worker.job.result.completed_at is None
    assert _messages(worker) == [
        "Albums: 1 -> 2 (+1, -0, skipped 0).",
        "Tracks: 5 -> 3 (+0, -2, skipped 1).",
        "Analysis completed. Run run-1; backup /backup.",
    ]


@dataclass
class EventClient:
    """Keep the existing SDK hook's previous-callback return contract.

    Args:
        callback: Current hook owner, restored explicitly by the facade.
    """

    callback: EventCallback | None = None

    def set_event_callback(
        self, callback: EventCallback | None
    ) -> EventCallback | None:
        """Swap an explicit callback using the original SDK return convention.

        Args:
            callback: New owner or none to clear the hook.

        Returns:
            The previously installed callback, without invoking either owner.
        """
        previous = self.callback
        self.callback = callback
        return previous


def test_optional_sdk_hook_preserves_binding_and_restoration() -> None:
    """Observe both absence of a hook and the original previous-owner convention."""
    assert spotify_event_setter(None) is None
    assert spotify_event_setter(cast(Spotify, object())) is None
    first, second = _worker("first"), _worker("second")
    client = EventClient(first.echo)
    setter = spotify_event_setter(cast(Spotify, client))
    assert setter is not None
    previous = setter(second.echo)
    assert previous == first.echo
    assert client.callback == second.echo
    assert client.callback is not None
    client.callback("SDK event")
    setter(previous)
    assert client.callback == first.echo
    assert _messages(first) == []
    assert _messages(second) == ["SDK event"]


def test_parallel_callbacks_and_cancellation_keep_distinct_owners() -> None:
    """Share the registry lock while preserving each context's sink and signal."""
    lock = Lock()
    first, second = _worker("first", lock), _worker("second", lock)
    with ThreadPoolExecutor(max_workers=2) as executor:
        left = executor.submit(first.echo, "left")
        right = executor.submit(second.echo, "right")
        left.result(timeout=5)
        right.result(timeout=5)
    first.job.cancel_event.set()
    assert second.job.cancel_event.is_set() is False
    assert _messages(first) == ["left"]
    assert _messages(second) == ["right"]
    assert isinstance(first.append, LogRecorder)
    assert first.append.calls[0][0] is first.job
