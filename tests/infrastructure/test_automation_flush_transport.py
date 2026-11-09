"""Verify the standard-library policy codec and real bounded HTTP owner."""

import io
import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from spotify_manager.application.automation_run import refresh_flush_mode
from spotify_manager.application.automation_values import AutomationError
from spotify_manager.application.automation_values import DeadlineReachedError
from spotify_manager.domain.flush_mode import QueueCounts
from spotify_manager.infrastructure.automation_records import flush_observation
from tests.infrastructure.test_automation_http_contracts import Transport
from tests.support.automation_flush import flush_payload
from tests.support.runtime_resources import MessageList


@pytest.mark.parametrize(
    "change",
    [
        {"control": "invalid"},
        {"control": []},
        {"automatic_active": 1},
        {"active": 0},
        {"active": True},
        {"queue_tracks": True},
        {"queue_tracks": -1},
        {"queue_2_tracks": -1},
        {"queue_tracks": None},
        {"queue_2_tracks": "10"},
        {"checked_at": "invalid"},
        {"checked_at": "2026-11-09"},
        {"attempted_at": 1},
        {"error": []},
    ],
)
def test_policy_codec_rejects_invalid_successes(change: dict[str, object]) -> None:
    """Malformed or inconsistent response fields must never report fresh success.

    Args:
        change: One independent malformed external field.
    """
    with pytest.raises(AutomationError, match="Flush Mode"):
        flush_observation({**flush_payload(), **change})


@pytest.mark.parametrize("raw", [None, [], "status", False])
def test_policy_codec_requires_an_object(raw: object) -> None:
    """Reject non-object policy responses.

    Args:
        raw: Malformed external response container.
    """
    with pytest.raises(AutomationError, match="invalid status"):
        flush_observation(raw)


def test_codec_normalizes_dates_and_retains_manual_override() -> None:
    """Force Off remains effective while automatic activation is observed."""
    state = flush_observation(
        {
            **flush_payload(),
            "control": "off",
            "automatic_active": True,
            "checked_at": "2026-11-09T01:00:00+01:00",
        }
    )
    assert not state.active and state.automatic_active
    assert state.counts == QueueCounts(100, 50)
    assert state.checked_at == "2026-11-09T00:00:00+00:00"


def test_status_uses_get_and_live_check_retries_gateway_failure() -> None:
    """Keep authenticated GET read-only and reuse existing transient POST retries."""
    raw = json.dumps(flush_payload()).encode()
    failure = HTTPError("https://space.test", 503, "offline", Message(), io.BytesIO())
    transport = Transport([raw, failure, raw])
    client = transport.client()
    assert client.flush_mode_status() == client.check_flush_mode()
    paths = []
    for request, _ in transport.requests:
        paths.append((request.get_method(), request.full_url))
    assert paths == [
        ("GET", "https://space.test/base/flush-mode"),
        ("POST", "https://space.test/base/flush-mode/check"),
        ("POST", "https://space.test/base/flush-mode/check"),
    ]
    assert transport.waits == [20]
    assert all(response.closed for response in transport.opened)


def test_returned_failure_retries_until_the_real_maintenance_deadline() -> None:
    """A stale HTTP 200 cannot become green or run past the bounded deadline."""
    raw = json.dumps({**flush_payload(), "error": "Spotify unavailable"}).encode()
    transport = Transport([raw], advance=True)
    output: list[str] = []
    with pytest.raises(DeadlineReachedError):
        refresh_flush_mode(transport.client(remaining=5), MessageList(output))
    assert transport.waits == [5]
    assert len(transport.requests) == 1
    assert len(output) == 1 and "Spotify unavailable" in output[0]
