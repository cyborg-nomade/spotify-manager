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
