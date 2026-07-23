"""Shared-password gate for the deployed web app.

Kept free of any FastAPI import so it depends only on Starlette (and the
standard library), which keeps it importable and unit-testable on its own.
"""

import hmac

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


# Paths reachable without the password (shell pages, liveness, favicon).
OPEN_PATHS = frozenset(
    {
        "/",
        "/index.html",
        "/genre-reveal",
        "/genre-reveal/",
        "/health",
        "/favicon.ico",
    }
)


class PasswordMiddleware(BaseHTTPMiddleware):
    """Require a shared password header on every non-open request.

    The expected value is passed in from ``APP_PASSWORD``. If it is ``None`` the
    gate is disabled (handy for local development); always set it in a
    deployment. Open paths and CORS preflight requests are never gated.
    """

    def __init__(self, app: ASGIApp, password: str | None) -> None:
        """Store the configured password (or ``None`` to disable the gate)."""
        super().__init__(app)
        self._password = password

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201
        """Allow open paths and preflight; otherwise check the header."""
        if (
            self._password is None
            or request.method == "OPTIONS"
            or request.url.path in OPEN_PATHS
        ):
            return await call_next(request)

        supplied = request.headers.get("x-app-password", "")
        if hmac.compare_digest(supplied, self._password):
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
