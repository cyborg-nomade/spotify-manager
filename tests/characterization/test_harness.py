"""Check that the recording harness detects, rather than masks, regressions."""

import socket
from pathlib import Path

import pytest

from spotify_manager.settings import Settings
from tests.support.effects import EffectInterruptedError
from tests.support.effects import Fault
from tests.support.effects import Responses
from tests.support.effects import Trace
from tests.support.isolation import FILES
from tests.support.isolation import ROOT


@pytest.mark.parametrize("phase,accepted", [("before", []), ("after", ["track"])])
def test_faults_distinguish_rejection_from_lost_acknowledgement(
    tmp_path, phase, accepted
):
    remote = []
    trace = Trace(tmp_path, Fault("add", phase))
    add = trace.wrap("add", remote.append)
    with pytest.raises(EffectInterruptedError):
        add("track")
    assert remote == accepted
    assert trace.fired
    # The fault is one-shot; it cannot inadvertently fail every retry.
    add("retry")
    assert remote == [*accepted, "retry"]


def test_trace_copies_mutable_values_at_each_observation(tmp_path):
    trace = Trace(tmp_path)
    state = {"pending": ["track"]}
    trace.record("checkpoint", "accepted", state)
    state["pending"].clear()
    assert trace.events == [
        {
            "operation": "checkpoint",
            "phase": "accepted",
            "value": {"pending": ["track"]},
        }
    ]


def test_scripted_pages_and_errors_are_strict():
    pages = Responses(
        {"items": [{"id": "a"}], "next": "page-2"},
        OSError("temporary"),
        {"items": [], "next": None},
    )
    assert pages(offset=0)["next"] == "page-2"
    with pytest.raises(OSError, match="temporary"):
        pages(offset=1)
    assert pages(offset=1) == {"items": [], "next": None}
    with pytest.raises(AssertionError, match="exhausted"):
        pages(offset=2)
    assert [kwargs["offset"] for _, kwargs in pages.calls] == [0, 1, 1, 2]


def test_nth_operation_fault_is_not_shifted_by_unrelated_calls(tmp_path):
    trace = Trace(tmp_path, Fault("checkpoint", "after", 2))
    save = trace.wrap("checkpoint", lambda value: value)
    save("first")
    trace.wrap("audit", lambda: None)()
    with pytest.raises(EffectInterruptedError):
        save("second")
    assert trace.counts == {"checkpoint": 2, "audit": 1}


@pytest.mark.parametrize("method", ["getaddrinfo", "gethostbyname"])
def test_unexpected_dns_is_blocked(method):
    args = ("example.invalid", 443) if method == "getaddrinfo" else ("example.invalid",)
    with pytest.raises(AssertionError, match="Unexpected network"):
        getattr(socket, method)(*args)


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_outbound_sockets_are_blocked(method):
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match="Unexpected network"):
            getattr(connection, method)(("127.0.0.1", 9))


@pytest.mark.parametrize(
    "path",
    [
        ROOT / ".env",
        FILES / "YourLibrary.json",
        ROOT / "spotify_manager" / "auth" / "spotipy_token_cache.json",
    ],
)
@pytest.mark.parametrize("mode", ["r", "w"])
def test_operator_files_cannot_be_opened(path, mode):
    with pytest.raises(AssertionError, match="Operator file access"):
        with path.open(mode):
            pytest.fail("The guard must run before opening the file")


def test_isolated_settings_never_load_operator_dotenv():
    assert Settings.model_config["env_file"] is None
    settings = Settings()
    assert settings.spotipy_client_secret == "test-secret"
    assert settings.lastfm_api_key == "test-lastfm-key"
    assert not Path.cwd().is_relative_to(ROOT)
