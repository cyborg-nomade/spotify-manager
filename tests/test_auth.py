"""Tests for the deployment password middleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from spotify_manager._auth import PasswordMiddleware


def password_protected_client() -> TestClient:
    app = FastAPI()
    app.add_middleware(PasswordMiddleware, password="correct-password")

    @app.get("/auth/check")
    def auth_check() -> dict[str, str]:
        return {"status": "ok"}

    return TestClient(app)


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
