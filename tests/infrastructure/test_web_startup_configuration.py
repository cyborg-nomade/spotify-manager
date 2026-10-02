"""Protect original direct-peer rules and deployment environment composition."""

import logging
from pathlib import Path

import pytest

from spotify_manager.bootstrap.web import environment
from spotify_manager.bootstrap.web import managed_path
from spotify_manager.infrastructure.web_peer import is_loopback


@pytest.mark.parametrize(
    "host,expected",
    [
        (None, False),
        ("LOCALHOST", True),
        ("127.0.0.1", True),
        ("127.1.2.3", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("192.168.1.1", False),
        ("malformed", False),
        ("", False),
    ],
)
def test_only_original_direct_peers_qualify(host: str | None, expected: bool) -> None:
    """Retain the original ipaddress and localhost qualifications.

    Args:
        host: Original direct socket peer.
        expected: Original local-development qualification.
    """
    assert is_loopback(host) is expected


@pytest.mark.parametrize("password", [None, "", "secret"])
@pytest.mark.parametrize("deployed", [False, True])
def test_original_password_environment(
    password: str | None,
    deployed: bool,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Preserve disabled warning, falsey credentials and Space deployment detection.

    Args:
        password: Original gate configuration.
        deployed: Original Space environment qualification.
        monkeypatch: Isolated environment overrides.
        caplog: Recorded original disabled-gate warning.
    """
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    if password is not None:
        monkeypatch.setenv("APP_PASSWORD", password)
    monkeypatch.setenv("AUTOMATION_TOKEN", "token")
    monkeypatch.setenv("SPACE_ID", "space" if deployed else "")
    monkeypatch.delenv("SPACE_HOST", raising=False)
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        result = environment()
    assert result.password == (password or None)
    assert result.automation_token == "token"
    assert result.allow_loopback is not deployed
    assert bool(caplog.records) is (not bool(password))


def test_original_path_override_keeps_empty_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Distinguish original missing path variables from explicitly empty values.

    Args:
        monkeypatch: Isolated environment overrides.
    """
    monkeypatch.delenv("ITEM6_MANAGED_PATH", raising=False)
    default = Path("original.json")
    assert managed_path("ITEM6_MANAGED_PATH", default) == default
    monkeypatch.setenv("ITEM6_MANAGED_PATH", "")
    assert managed_path("ITEM6_MANAGED_PATH", default) == Path("")
