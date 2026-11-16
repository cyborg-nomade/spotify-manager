"""Serve real explorer routes/assets over synthetic, independently published data."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from spotify_manager._auth import PasswordMiddleware
from spotify_manager.interfaces.http.listening import router
from tests.support.listening import listening_fixture
from tests.support.listening import scrobble


FRONTEND = Path(__file__).resolve().parents[2] / "spotify_manager" / "frontend"


def browser_rows() -> list[dict[str, object]]:
    """Create varied histories, including hostile display text and old favorites."""
    rows = []
    first = datetime(2023, 1, 1, 12, tzinfo=UTC)
    for index in range(780):
        when = first + timedelta(days=index, hours=index % 10)
        artist = ("Alpha", "Béta", "Gamma", "Delta", "Old Favorite")[index % 5]
        if index > 650 and artist == "Old Favorite":
            artist = "New Favorite"
        rows.append(
            scrobble(
                when.isoformat(), artist, f"Song {index % 17}", f"Record {index % 7}"
            )
        )
    rows.append(
        scrobble(
            "2024-12-01T13:00:00",
            '<img src=x onerror="window.musicNameExecuted=true">',
            "=formula",
            "",
        )
    )
    return rows


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own only synthetic storage and the real analytics runtime."""
    with TemporaryDirectory(prefix="listening-browser-") as directory:
        fixture = listening_fixture(Path(directory))
        fixture.publish(browser_rows())
        app.state.listening = fixture.runtime
        try:
            yield
        finally:
            await fixture.runtime.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(PasswordMiddleware, password="browser-test-password")
app.include_router(router)
app.mount("/lastfm/assets", StaticFiles(directory=FRONTEND / "lastfm-assets"))


@app.get("/health")
def health() -> dict[str, str]:
    """Provide the same public startup probe as the real web wrapper."""
    return {"status": "ok"}


@app.get("/auth/check")
def auth_check() -> dict[str, str]:
    """Let the real password middleware authenticate the browser fixture."""
    return {"status": "ok"}


@app.get("/lastfm")
def shell() -> FileResponse:
    """Serve the actual packaged explorer shell."""
    return FileResponse(FRONTEND / "lastfm.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8018)
