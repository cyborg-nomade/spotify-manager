"""Verify bounded count retries and policy observations before freshness checks."""

from zoneinfo import ZoneInfo

import pytest

from spotify_manager.application import automation_run
from spotify_manager.application.automation_values import JOBS
from spotify_manager.application.automation_values import AutomationError
from tests.application.automation_memory import FixedNowResource
from tests.application.automation_memory import fixed_now
from tests.application.test_automation_stage_boundaries import ScriptedSpace
from tests.support.automation_flush import flush_payload
from tests.support.runtime_resources import MessageList


def test_failed_observation_retries_without_changing_control() -> None:
    """A returned count failure is retried without any override write."""
    failed = {**flush_payload(), "error": "Counts unavailable", "control": "off"}
    successful = {**flush_payload(), "control": "off", "automatic_active": True}
    client = ScriptedSpace([failed, failed, successful])
    output: list[str] = []
    automation_run.refresh_flush_mode(client, MessageList(output))
    assert client.events == [
        ("POST", "/flush-mode/check", True, None),
        20,
        ("POST", "/flush-mode/check", True, None),
        20,
        ("POST", "/flush-mode/check", True, None),
    ]
    assert len(output) == 3 and "control: off" in output[-1]
    assert all("Retrying" in line for line in output[:2])


def test_incomplete_success_cannot_be_reported_as_a_check() -> None:
    """An unobserved status is valid for GET but cannot masquerade as a check."""
    raw = {**flush_payload(), "queue_tracks": None, "queue_2_tracks": None}
    raw.update(checked_at=None, attempted_at=None)
    client = ScriptedSpace([raw])
    with pytest.raises(AutomationError, match="no complete observation"):
        automation_run.refresh_flush_mode(client, MessageList([]))


def test_count_check_precedes_library_jobs_even_when_a_job_pauses() -> None:
    """Checking policy is independent of all four library refresh outcomes."""
    client = ScriptedSpace([{}, flush_payload(), {"files": []}])
    # Expired transport boundaries are tested with the real HTTP owner separately.
    client.responses.extend([{"job_id": "history"}, {"status": "paused"}])
    result = automation_run.nightly_refresh(
        client,
        JOBS,
        fixed_now(),
        ZoneInfo("Europe/Berlin"),
        FixedNowResource(),
        MessageList([]),
    )
    assert result == 0
    assert client.events[:3] == [
        ("GET", "/health", True, None),
        ("POST", "/flush-mode/check", True, None),
        ("GET", "/library-mirrors/status", True, None),
    ]
    assert client.events[3] == ("POST", JOBS[0].start_path, True, None)
