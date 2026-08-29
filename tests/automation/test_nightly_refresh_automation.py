from __future__ import annotations

import importlib.util
import sys
from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / ".github" / "scripts" / "nightly_refresh.py"
)
WORKFLOW_PATH = SCRIPT_PATH.parents[1] / "workflows" / "nightly-library-refresh.yml"


@pytest.fixture(scope="module")
def nightly() -> ModuleType:
    spec = importlib.util.spec_from_file_location("nightly_refresh_script", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_maintenance_deadline_tracks_berlin_dst(nightly: ModuleType) -> None:
    winter = datetime(2026, 1, 15, 22, 30, tzinfo=UTC)
    summer = datetime(2026, 7, 15, 22, 30, tzinfo=UTC)
    manual = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)

    assert nightly.maintenance_deadline(winter) == datetime(
        2026, 1, 16, 4, 0, tzinfo=UTC
    )
    assert nightly.maintenance_deadline(summer) == datetime(
        2026, 7, 16, 3, 0, tzinfo=UTC
    )
    assert nightly.maintenance_deadline(manual) == datetime(
        2026, 7, 15, 15, 0, tzinfo=UTC
    )
    assert nightly.scheduled_window_is_open(summer)
    assert not nightly.scheduled_window_is_open(manual)
    assert nightly.maintenance_window_start(summer) == datetime(
        2026, 7, 15, 20, 0, tzinfo=UTC
    )
    after_midnight = datetime(2026, 7, 15, 23, 0, tzinfo=UTC)
    assert nightly.maintenance_window_start(after_midnight) == datetime(
        2026, 7, 15, 20, 0, tzinfo=UTC
    )


def test_job_sets_select_incremental_or_full_rebuild(nightly: ModuleType) -> None:
    assert "full_rebuild=false" in nightly.JOBS[1].start_path
    assert "full_rebuild=true" in nightly.FULL_REBUILD_JOBS[1].start_path
    assert len(nightly.JOBS) == len(nightly.FULL_REBUILD_JOBS) == 4


def test_required_environment_never_allows_missing_secrets(
    nightly: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_SPACE_TOKEN", raising=False)
    monkeypatch.delenv("AUTOMATION_TOKEN", raising=False)

    with pytest.raises(
        nightly.AutomationError, match="HF_SPACE_TOKEN.*AUTOMATION_TOKEN"
    ):
        nightly.required_environment()

    monkeypatch.setenv("SPACE_URL", "https://example.test/app")
    monkeypatch.setenv("HF_SPACE_TOKEN", "hf-secret")
    monkeypatch.setenv("AUTOMATION_TOKEN", "automation-secret")
    assert nightly.required_environment() == (
        "https://example.test/app/",
        "hf-secret",
        "automation-secret",
    )


class FakeClient:
    def __init__(self, responses, *, remaining: float = 100) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[str, str]] = []
        self.sleeps: list[int] = []
        self.remaining = remaining
        self.deadline = datetime(2026, 8, 25, 3, 0, tzinfo=UTC)

    def request(self, method, path, **_kwargs):
        self.calls.append((method, path))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def remaining_seconds(self):
        return self.remaining


def test_start_job_reconnects_to_its_existing_job(nightly: ModuleType) -> None:
    spec = nightly.JOBS[1]
    client = FakeClient([nightly.ApiError(409, {"detail": {"job_id": "existing"}})])

    assert nightly.start_job(client, spec) == "existing"


def test_scrobble_job_waits_for_an_unrelated_playlist_job(
    nightly: ModuleType,
) -> None:
    client = FakeClient(
        [
            nightly.ApiError(
                409,
                {"detail": {"job_id": "other", "command": "found_art"}},
            ),
            {"job_id": "history"},
        ]
    )

    assert nightly.start_job(client, nightly.JOBS[0]) == "history"
    assert client.sleeps == [nightly.BLOCKED_RETRY_SECONDS]


def test_poll_job_reports_completion_and_space_restart(nightly: ModuleType) -> None:
    spec = nightly.JOBS[2]
    completed = FakeClient(
        [
            {"status": "running", "detail": "working"},
            {"status": "completed", "detail": "done"},
        ]
    )
    assert nightly.poll_job(completed, spec, "job") == "completed"
    assert completed.sleeps == [nightly.POLL_SECONDS]

    lost = FakeClient([nightly.ApiError(404, {"detail": "missing"})])
    with pytest.raises(nightly.JobLostError, match="Space restart"):
        nightly.poll_job(lost, spec, "job")

    cancelled = FakeClient([{"status": "cancelled", "detail": "Progress was saved."}])
    assert nightly.poll_job(cancelled, spec, "job") == "paused"


def test_poll_job_cancels_at_the_deadline(nightly: ModuleType) -> None:
    spec = nightly.JOBS[3]
    client = FakeClient([{"status": "cancelling"}], remaining=0)

    assert nightly.poll_job(client, spec, "job") == "deadline"
    assert client.calls == [("POST", spec.cancel_path.format(job_id="job"))]


def test_nightly_refresh_stops_cleanly_after_a_rate_limit(
    nightly: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeClient([{"status": "ok"}])
    outcomes = iter(["completed", "paused"])
    monkeypatch.setattr(nightly, "run_job", lambda _client, _spec: next(outcomes))

    assert nightly.run_nightly_refresh(client) == 0
    assert client.calls == [("GET", "/health")]


def test_duplicate_schedule_skips_when_all_artifacts_are_fresh(
    nightly: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = [
        {
            "filename": filename,
            "exists": True,
            "updated_at": "2026-08-29T00:30:00+00:00",
        }
        for filename in nightly.DURABLE_ARTIFACT_FILENAMES
    ]
    client = FakeClient([{"status": "ok"}, {"files": files}])
    monkeypatch.setattr(
        nightly,
        "run_job",
        lambda *_args: pytest.fail("fresh duplicate must not start jobs"),
    )

    assert nightly.run_nightly_refresh(
        client,
        freshness_threshold=datetime(2026, 8, 28, 20, 0, tzinfo=UTC),
    ) == 0
    assert client.calls == [
        ("GET", "/health"),
        ("GET", "/library-mirrors/status"),
    ]


def test_stale_artifact_does_not_suppress_scheduled_refresh(
    nightly: ModuleType,
) -> None:
    files = [
        {
            "filename": filename,
            "exists": True,
            "updated_at": (
                "2026-08-28T19:59:00+00:00"
                if filename == "artists_total.json"
                else "2026-08-29T00:30:00+00:00"
            ),
        }
        for filename in nightly.DURABLE_ARTIFACT_FILENAMES
    ]
    client = FakeClient([{"files": files}])

    assert not nightly.durable_artifacts_are_fresh(
        client,
        datetime(2026, 8, 28, 20, 0, tzinfo=UTC),
    )


def test_connection_check_requires_all_durable_artifacts(
    nightly: ModuleType,
) -> None:
    files = [{"filename": spec.label, "exists": True} for spec in nightly.JOBS]
    client = FakeClient(
        [
            {"status": "ok"},
            {"status": "ok"},
            {"files": files},
        ]
    )

    assert nightly.run_connection_check(client) == 0

    missing = FakeClient(
        [
            {"status": "ok"},
            {"status": "ok"},
            {"files": files[:-1]},
        ]
    )
    with pytest.raises(nightly.AutomationError, match="status is incomplete"):
        nightly.run_connection_check(missing)


def test_workflow_schedules_weekend_full_rebuild() -> None:
    workflow = WORKFLOW_PATH.read_text()

    assert 'cron: "17 19 * * 0-5"' in workflow
    assert 'cron: "17 0 * * 1-6"' in workflow
    assert 'cron: "37 19 * * 6"' in workflow
    assert 'cron: "37 0 * * 0"' in workflow
    assert workflow.count('timezone: "Europe/Berlin"') == 4
    assert "--full-rebuild" in workflow
    assert "--scheduled" in workflow
