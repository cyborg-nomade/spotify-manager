"""Shared-password gate for the deployed web app.

Kept free of any FastAPI import so it depends only on Starlette (and the
standard library), which keeps it importable and unit-testable on its own.
"""

import hmac
from ipaddress import ip_address

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response
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

    def __init__(
        self,
        app: ASGIApp,
        password: str | None,
        *,
        automation_token: str | None = None,
        allow_any_loopback_password: bool = False,
    ) -> None:
        """Store the configured password (or ``None`` to disable the gate)."""
        super().__init__(app)
        self._password = password
        self._automation_token = automation_token
        self._allow_any_loopback_password = allow_any_loopback_password

    @staticmethod
    def _is_loopback(request: Request) -> bool:
        """Trust only the direct socket peer, never forwarded client headers."""
        if request.client is None:
            return False
        host = request.client.host.casefold()
        if host == "localhost":
            return True
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Allow open paths and preflight; otherwise check the header."""
        if (
            self._password is None
            or request.method == "OPTIONS"
            or request.url.path in OPEN_PATHS
        ):
            return await call_next(request)

        supplied = request.headers.get("x-app-password", "")
        automation_token = request.headers.get("x-automation-token", "")
        if (
            automation_token
            and self._automation_token
            and hmac.compare_digest(automation_token, self._automation_token)
        ):
            return await call_next(request)
        if (
            supplied
            and self._allow_any_loopback_password
            and self._is_loopback(request)
        ):
            return await call_next(request)
        if hmac.compare_digest(supplied, self._password):
            return await call_next(request)

        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
