"""Shared-password gate for the deployed web app.

Kept free of any FastAPI import so it depends only on Starlette (and the
standard library), which keeps it importable and unit-testable on its own.
"""

import hmac
from functools import partial

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response
from starlette.types import ASGIApp

from spotify_manager.domain.web_access import OPEN_PATHS as OPEN_PATHS
from spotify_manager.domain.web_access import credential_matches
from spotify_manager.domain.web_access import is_open
from spotify_manager.infrastructure.web_peer import is_loopback


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
        """Store the configured password (or ``None`` to disable the gate).

        Args:
            app: Original wrapped ASGI application.
            password: Original shared password, or none to disable the gate.
            automation_token: Original optional automation credential.
            allow_any_loopback_password: Enable local socket peer bypass.
        """
        super().__init__(app)
        self._password = password
        self._automation_token = automation_token
        self._allow_any_loopback_password = allow_any_loopback_password

    @staticmethod
    def _is_loopback(request: Request) -> bool:
        """Trust only the direct socket peer, never forwarded client headers."""
        host = request.client.host if request.client else None
        return is_loopback(host)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        """Allow open paths and preflight; otherwise check the header.

        Args:
            request: Original incoming Starlette request.
            call_next: Original next request handler.

        Returns:
            Original dispatch result.
        """
        if self._password is None or request.method == "OPTIONS":
            return await call_next(request)
        if is_open(self._password, request.method, request.url.path):
            return await call_next(request)
        assert self._password is not None
        supplied = request.headers.get("x-app-password", "")
        automation = request.headers.get("x-automation-token", "")
        allowed = credential_matches(
            supplied,
            self._password,
            automation,
            self._automation_token,
            self._allow_any_loopback_password,
            partial(self._is_loopback, request),
            hmac.compare_digest,
        )
        if allowed:
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
