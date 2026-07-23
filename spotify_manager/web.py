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
from threading import Lock

from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import Response
from spotipy.exceptions import SpotifyException

# UFI
from spotify_manager._auth import PasswordMiddleware
from spotify_manager.api import ClientDep
from spotify_manager.api import app
from spotify_manager.routines import genre_reveal
from spotify_manager.routines.review_album_limits import format_retry_delay
from spotify_manager.routines.review_album_limits import get_retry_after_seconds
from spotify_manager.settings import Settings


FRONTEND_DIR = Path(__file__).resolve().parent / "frontend"
INDEX_HTML = FRONTEND_DIR / "index.html"
GENRE_REVEAL_HTML = FRONTEND_DIR / "genre-reveal.html"
GENRE_REVEAL_STATE_PATH = Path(
    os.environ.get(
        "GENRE_REVEAL_STATE_PATH",
        genre_reveal.DEFAULT_STATE_PATH,
    )
)
GENRE_REVEAL_LOG_PATH = Path(
    os.environ.get(
        "GENRE_REVEAL_LOG_PATH",
        genre_reveal.DEFAULT_LOG_PATH,
    )
)
_genre_reveal_state_lock = Lock()
_genre_reveal_run_lock = Lock()


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


@app.get("/genre-reveal", include_in_schema=False)
def genre_reveal_page() -> FileResponse:
    """Serve the Every Noise nearest-neighbour route."""
    return FileResponse(GENRE_REVEAL_HTML)


@app.get(
    "/genre-reveal/state",
    response_model=genre_reveal.GenreRevealState,
)
def get_genre_reveal_state() -> genre_reveal.GenreRevealState:
    """Return persisted Every Noise route progress."""
    try:
        with _genre_reveal_state_lock:
            return genre_reveal.load_genre_reveal_state(GENRE_REVEAL_STATE_PATH)
    except genre_reveal.GenreRevealStateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put(
    "/genre-reveal/state",
    response_model=genre_reveal.GenreRevealState,
)
def put_genre_reveal_state(
    update: genre_reveal.GenreRevealStateUpdate,
) -> genre_reveal.GenreRevealState:
    """Atomically replace persisted Every Noise route progress."""
    try:
        with _genre_reveal_state_lock:
            return genre_reveal.save_genre_reveal_state(
                update,
                GENRE_REVEAL_STATE_PATH,
            )
    except genre_reveal.GenreRevealStateError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get(
    "/genre-reveal/source",
    response_model=genre_reveal.GenreRevealSourcePreview,
)
def get_genre_reveal_source(
    slug: str,
    name: str,
) -> genre_reveal.GenreRevealSourcePreview:
    """Resolve the primary Spotify playlist before the user starts a run."""
    try:
        return genre_reveal.discover_genre_source(slug, name)
    except genre_reveal.GenreRevealSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/genre-reveal/run-next",
    response_model=genre_reveal.GenreRevealRunResult,
)
def run_next_genre_reveal(
    request: genre_reveal.GenreRevealRunRequest,
    client: ClientDep,
) -> genre_reveal.GenreRevealRunResult:
    """Save and sample the first incomplete genre selected by the route."""
    if not _genre_reveal_run_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail="another Genre Reveal operation is already running",
        )

    try:
        with _genre_reveal_state_lock:
            state = genre_reveal.load_genre_reveal_state(GENRE_REVEAL_STATE_PATH)
            if request.slug in state.completed:
                raise HTTPException(
                    status_code=409,
                    detail=f"{request.name} is already completed",
                )

        destination_playlist_id = genre_reveal.parse_destination_playlist_id(
            Settings().genre_reveal_playlist
        )
        result = genre_reveal.process_next_genre(
            client,
            request.slug,
            request.name,
            destination_playlist_id,
            log_path=GENRE_REVEAL_LOG_PATH,
        )

        with _genre_reveal_state_lock:
            genre_reveal.mark_genre_completed(
                request.slug,
                GENRE_REVEAL_STATE_PATH,
            )
        return result
    except HTTPException:
        raise
    except genre_reveal.GenreRevealConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except genre_reveal.GenreRevealSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except (
        genre_reveal.GenreRevealStateError,
        genre_reveal.GenreRevealLogError,
    ) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SpotifyException as exc:
        if exc.http_status == 429:
            retry_delay = format_retry_delay(get_retry_after_seconds(exc))
            raise HTTPException(
                status_code=429,
                detail=(
                    "Spotify rate limit reached after trying all configured "
                    f"credentials. Try again {retry_delay}."
                ),
            ) from exc
        status_code = exc.http_status if exc.http_status in {400, 403} else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    finally:
        _genre_reveal_run_lock.release()


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    """No favicon; answer 204 so browsers stop asking (and stay un-gated)."""
    return Response(status_code=204)


def serve(host: str = "0.0.0.0", port: int = 7860) -> None:  # noqa: S104
    """Run the gated web app with uvicorn (entry point for deployment)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)
