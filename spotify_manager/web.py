"""Deployment wrapper: password gate + mobile frontend around the FastAPI app.

This module imports the pure API defined in :mod:`spotify_manager.api` and,
without modifying it, adds two deployment concerns:

* a lightweight shared-password gate (checked against the ``APP_PASSWORD``
  environment variable via the ``X-App-Password`` request header), and
* the single-page mobile frontend, served at ``/``.

Run in production with::

    uvicorn spotify_manager.web:app --host 0.0.0.0 --port 7860

The plain API (no gate, no frontend) is still available unchanged as
``spotify_manager.api:app`` for local use and tests.
"""

import logging
import os
from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.responses import Response

# UFI
from spotify_manager._auth import PasswordMiddleware
from spotify_manager.api import app


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"


_password = os.environ.get("APP_PASSWORD") or None
if _password is None:
    logging.getLogger("uvicorn.error").warning(
        "APP_PASSWORD is not set — the password gate is DISABLED. "
        "Set APP_PASSWORD before deploying."
    )

app.add_middleware(PasswordMiddleware, password=_password)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Serve the single-page mobile frontend."""
    return FileResponse(INDEX_HTML)


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """No favicon; answer 204 so browsers stop asking (and stay un-gated)."""
    return Response(status_code=204)


def serve(host: str = "0.0.0.0", port: int = 7860) -> None:  # noqa: S104
    """Run the gated web app with uvicorn (entry point for deployment)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)
