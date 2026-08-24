"""Tests for the deployment password middleware."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spotify_manager._auth import PasswordMiddleware


def password_protected_client(
    *,
    automation_token: str | None = None,
    allow_any_loopback_password: bool = False,
    client_host: str = "testclient",
) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        PasswordMiddleware,
        password="correct-password",
        automation_token=automation_token,
        allow_any_loopback_password=allow_any_loopback_password,
    )

    @app.get("/auth/check")
    def auth_check() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app, client=(client_host, 50000))


def test_auth_check_requires_matching_password_header() -> None:
    client = password_protected_client()

    assert client.get("/auth/check").status_code == 401
    assert (
        client.get(
            "/auth/check",
            headers={"X-App-Password": "wrong-password"},
        ).status_code
        == 401
    )
    response = client.get(
        "/auth/check",
        headers={"X-App-Password": "correct-password"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_auth_check_accepts_the_separate_automation_token() -> None:
    client = password_protected_client(automation_token="scheduled-secret")

    assert (
        client.get(
            "/auth/check",
            headers={"X-Automation-Token": "wrong-secret"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/auth/check",
            headers={"X-Automation-Token": "scheduled-secret"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize("client_host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_accepts_any_non_empty_password_when_enabled(
    client_host: str,
) -> None:
    client = password_protected_client(
        allow_any_loopback_password=True,
        client_host=client_host,
    )

    assert client.get("/auth/check").status_code == 401
    assert (
        client.get(
            "/auth/check",
            headers={"X-App-Password": "anything"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize("client_host", ["10.20.38.210", "external.test"])
def test_non_loopback_still_requires_exact_password_when_relaxation_enabled(
    client_host: str,
) -> None:
    client = password_protected_client(
        allow_any_loopback_password=True,
        client_host=client_host,
    )

    assert (
        client.get(
            "/auth/check",
            headers={"X-App-Password": "anything"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/auth/check",
            headers={"X-App-Password": "correct-password"},
        ).status_code
        == 200
    )
