"""Protect original nightly API failures and delayed operational observations."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from spotify_manager.application import automation_run as workflow
from spotify_manager.application.automation_values import JOBS
from spotify_manager.application.automation_values import ApiError
from spotify_manager.application.automation_values import AutomationError
from spotify_manager.application.automation_values import JobSpec
from tests.application.automation_memory import fixed_now


@dataclass
class ScriptedSpace:
    """Supply original decoded response values and narrowed API failures.

    Args:
        responses: Original observations in request order.
        events: Original API requests and wait durations.
        deadline: Original maintenance boundary.
    """

    responses: list[object]
    events: list[object] = field(default_factory=list)
    deadline: datetime = datetime(2026, 9, 24, 3, tzinfo=UTC)

    def request(
        self,
        method: str,
        path: str,
        *,
        retry_transient: bool = True,
        deadline: datetime | None = None,
    ) -> object:
        """Observe the original ordered request and raw response.

        Args:
            method: Original HTTP verb.
            path: Original path and query.
            retry_transient: Original retry flag.
            deadline: Original optional grace deadline.

        Returns:
            Original raw decoded response.

        Raises:
            ApiError: Selected original HTTP failure.
        """
        self.events.append((method, path, retry_transient, deadline))
        result = self.responses.pop(0)
        if isinstance(result, ApiError):
            raise result
        return result

    def sleep(self, seconds: int) -> None:
        """Record original waits without blocking.

        Args:
            seconds: Original requested wait.
        """
        self.events.append(seconds)

    def remaining_seconds(self) -> float:
        """Supply positive original maintenance time.

        Returns:
            Remaining original seconds.
        """
        return 100


def discard(message: str) -> None:
    """Consume original presentation without replacing business stages.

    Args:
        message: Original progress output.
    """


@pytest.mark.parametrize("payload", [None, {}, {"detail": None}, {"detail": {}}])
def test_conflict_without_identity_waits_before_restart(payload: object) -> None:
    """Keep incomplete conflict details non-reconnectable.

    Args:
        payload: Original unchecked conflict response.
    """
    client = ScriptedSpace([ApiError(409, payload), {"job_id": "new"}])
    assert workflow.start_job(client, JOBS[0], discard) == "new"
    assert 60 in client.events


def test_start_propagates_non_conflict_status() -> None:
    """Retain original non-conflict HTTP failure identity."""
    error = ApiError(403, {})
    with pytest.raises(ApiError) as raised:
        workflow.start_job(ScriptedSpace([error]), JOBS[0], discard)
    assert raised.value is error


@pytest.mark.parametrize("status", [404, 409, 500])
def test_cancel_tolerates_only_original_statuses(status: int) -> None:
    """Keep original cancellation tolerances and separately observed grace clock.

    Args:
        status: Original cancellation failure status.
    """
    client = ScriptedSpace([ApiError(status, {})])
    if status == 500:
        with pytest.raises(ApiError):
            workflow.cancel_job(client, JOBS[0], "job", fixed_now, discard)
        return
    workflow.cancel_job(client, JOBS[0], "job", fixed_now, discard)


def unexpected_cancel(spec: JobSpec, identity: str) -> None:
    """Reject cancellation while original maintenance time remains.

    Args:
        spec: Unexpected cancellation route.
        identity: Unexpected active identity.

    Raises:
        AssertionError: Polling cancels before its original deadline.
    """
    raise AssertionError((spec, identity))


def test_poll_propagates_non_missing_http_status() -> None:
    """Translate only original missing handles into restart outcomes."""
    error = ApiError(403, {})
    with pytest.raises(ApiError) as raised:
        workflow.poll_job(
            ScriptedSpace([error]), JOBS[0], "job", unexpected_cancel, discard
        )
    assert raised.value is error


def test_poll_reports_only_changed_status() -> None:
    """Keep repeated active observations quiet while retaining every wait."""
    client = ScriptedSpace(
        [{"status": "running"}, {"status": "running"}, {"status": "completed"}]
    )
    output: list[str] = []
    assert (
        workflow.poll_job(client, JOBS[0], "job", unexpected_cancel, output.append)
        == "completed"
    )
    assert len(output) == 2 and client.events.count(20) == 2


def fresh_artifacts(threshold: datetime) -> bool:
    """Supply already refreshed original artifacts.

    Args:
        threshold: Original maintenance opening.

    Returns:
        Complete original freshness qualification.
    """
    return True


def unexpected_job(spec: JobSpec) -> str:
    """Reject job starts after original duplicate-trigger detection.

    Args:
        spec: Unexpected job manifest entry.

    Raises:
        AssertionError: A fresh duplicate trigger starts a routine.
    """
    raise AssertionError(spec)


def test_fresh_duplicate_skips_after_health_read() -> None:
    """Retain health before duplicate detection and suppress all routine starts."""
    client = ScriptedSpace([{}])
    assert (
        workflow.nightly_refresh(
            client,
            JOBS,
            fixed_now(),
            ZoneInfo("Europe/Berlin"),
            fresh_artifacts,
            unexpected_job,
            discard,
        )
        == 0
    )
    assert len(client.events) == 1


@pytest.mark.parametrize(
    "responses,message",
    [
        ([{}, None], "token"),
        (
            [
                {},
                {"status": "ok"},
                {"files": [{"filename": "lost", "exists": False}] * 4},
            ],
            "missing: lost",
        ),
        (
            [
                {},
                {"status": "ok"},
                {"files": [{"exists": True}] * 4},
                {},
            ],
            "state",
        ),
        (
            [
                {},
                {"status": "ok"},
                {"files": [{"exists": True}] * 4},
                {"revision": "sha"},
                None,
            ],
            "inspect",
        ),
        (
            [
                {},
                {"status": "ok"},
                {"files": [{"exists": True}] * 4},
                {"revision": "sha"},
                {"paths": {}},
            ],
            "No active",
        ),
        (
            [
                {},
                {"status": "ok"},
                {"files": [{"exists": True}] * 4},
                {"revision": "sha"},
                {"paths": {"/one-jobs": {}}},
                None,
            ],
            "Invalid active",
        ),
    ],
)
def test_connection_prerequisite_failures(
    responses: list[object], message: str
) -> None:
    """Keep original prerequisite order and narrowed diagnostics.

    Args:
        responses: Original ordered response sequence.
        message: Original visible failure fragment.
    """
    with pytest.raises(AutomationError, match=message):
        workflow.connection_check(ScriptedSpace(responses), discard)
