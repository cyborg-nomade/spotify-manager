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
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import Response

from spotify_manager._auth import PasswordMiddleware
from spotify_manager.application import listening_covers as cover_application
from spotify_manager.application import listening_origins as origin_application
from spotify_manager.application import listening_tags as tag_application
from spotify_manager.application.listening_covers import ListeningCoverEnrichment
from spotify_manager.application.listening_origins import ListeningOriginEnrichment
from spotify_manager.application.listening_tags import ListeningTagEnrichment
from spotify_manager.domain.web_access import LISTENING_ASSETS
from spotify_manager.domain.web_access import listening_asset_cache_control
from spotify_manager.infrastructure.listening.cover_cache import AlbumCoverCache
from spotify_manager.infrastructure.listening.library_runtime import LibraryRuntime
from spotify_manager.infrastructure.listening.origin_cache import ArtistOriginCache
from spotify_manager.infrastructure.listening.tag_cache import ArtistTagCache
from spotify_manager.interfaces.http.listening import router
from spotify_manager.interfaces.http.listening_origins import router as origin_router
from spotify_manager.interfaces.http.listening_quilt import router as quilt_router
from spotify_manager.interfaces.http.listening_sessions import router as session_router
from spotify_manager.interfaces.http.listening_tags import router as tag_router
from tests.support.listening import listening_fixture
from tests.support.listening import scrobble
from tests.support.listening_covers import FixtureCoverSource
from tests.support.listening_covers import cover_result
from tests.support.listening_library import publish_collection
from tests.support.listening_origins import FixtureOriginSource
from tests.support.listening_origins import origin_metadata
from tests.support.listening_tags import FixtureTagSource
from tests.support.listening_tags import tag_metadata


FRONTEND = Path(__file__).resolve().parents[2] / "spotify_manager" / "frontend"
LEGACY_ASSETS = {
    "explorer-v1.js": 'import "./charts-v1.js"; import "./tables-v1.js"; '
    "window.legacyExplorer = true;",
    "charts-v1.js": 'import "./eras-v1.js"; window.legacyCharts = true;',
    "tables-v1.js": "window.legacyTables = true;",
    "eras-v1.js": "window.legacyEras = true;",
    "explorer-v1.css": ".era-controls { pointer-events: none !important; }",
}
LEGACY_SHELL = """<!doctype html><html><head>
<link rel="stylesheet" href="/lastfm/assets/explorer-v1.css">
<script type="module" src="/lastfm/assets/explorer-v1.js"></script>
</head><body>Legacy cache fixture</body></html>"""


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


def cover_stage(root: Path, now: str) -> ListeningCoverEnrichment:
    """Own synthetic representative covers independently of published history."""
    cover_cache = AlbumCoverCache(root / "cover-cache")
    colors = (
        "#93674e",
        "#426e7c",
        "#837555",
        "#83616d",
        "#4b7770",
        "#656c87",
        "#9a694c",
    )
    for index in range(7):
        cover_cache.write(
            cover_result(
                f"Record {index}", "Alpha", fetched_at=now, color=colors[index]
            )
        )
        cover_cache.write(
            cover_result(
                f"Record {index}",
                "Béta",
                fetched_at=now,
                color=colors[(index + 3) % 7],
            )
        )
    cover_cache.write(cover_result("Record 0", "Gamma", "no_cover", fetched_at=now))
    cover_cache.write(cover_result("Record 1", "Delta", "ambiguous", 2, now))
    cover_cache.write(cover_result("Record 2", "Old Favorite", "incomplete", 1, now))
    cover_application.REQUEST_INTERVAL = 0.01
    return ListeningCoverEnrichment(cover_cache, FixtureCoverSource())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own only synthetic storage and the real analytics runtime."""
    with TemporaryDirectory(prefix="listening-browser-") as directory:
        fixture = listening_fixture(Path(directory))
        fixture.publish(browser_rows())
        publish_collection(
            fixture,
            "albums",
            [
                {
                    "artist": "Alpha",
                    "album": "Record 0",
                    "uri": "spotify:album:" + "a" * 22,
                },
                {
                    "artist": "Delta",
                    "album": "Record 2",
                    "uri": "spotify:album:" + "b" * 22,
                },
                {
                    "artist": "Delta",
                    "album": "Record 2",
                    "uri": "spotify:album:" + "c" * 22,
                },
            ],
        )
        publish_collection(
            fixture,
            "tracks",
            [
                {
                    "artist": '<img src=x onerror="window.musicNameExecuted=true">',
                    "track": "=formula",
                    "uri": "spotify:track:" + "d" * 22,
                },
            ],
        )
        app.state.listening = fixture.runtime
        app.state.listening_library = LibraryRuntime(fixture.service)
        cache = ArtistTagCache(Path(directory) / "tag-cache")
        cache.write(tag_metadata("Alpha"))
        cache.write(tag_metadata("Béta", ("Jazz",)))
        cache.write(tag_metadata("Gamma", (), "empty"))
        tag_application.REQUEST_INTERVAL = 0.01
        app.state.listening_tags = ListeningTagEnrichment(cache, FixtureTagSource())
        origin_cache = ArtistOriginCache(Path(directory) / "origin-cache")
        now = datetime.now(UTC).isoformat()
        for observation in (
            origin_metadata("Alpha", fetched_at=now),
            origin_metadata("Béta", ("GB",), fetched_at=now),
            origin_metadata("Gamma", ("GB", "US"), fetched_at=now),
            origin_metadata("Delta", ("US",), "ambiguous", 2, now),
            origin_metadata("Old Favorite", (), fetched_at=now),
            origin_metadata(
                '<img src=x onerror="window.musicNameExecuted=true">', fetched_at=now
            ),
        ):
            origin_cache.write(observation)
        origin_application.REQUEST_INTERVAL = 0.01
        app.state.listening_origins = ListeningOriginEnrichment(
            origin_cache, FixtureOriginSource()
        )
        app.state.listening_covers = cover_stage(Path(directory), now)
        try:
            yield
        finally:
            await app.state.listening_covers.close()
            await app.state.listening_origins.close()
            await app.state.listening_tags.close()
            await app.state.listening_library.close()
            await fixture.runtime.close()


app = FastAPI(lifespan=lifespan)
app.add_middleware(PasswordMiddleware, password="browser-test-password")
app.include_router(router)
app.include_router(tag_router)
app.include_router(origin_router)
app.include_router(quilt_router)
app.include_router(session_router)


@app.get("/lastfm/assets/{filename}")
def asset(filename: str, request: Request) -> Response:
    """Serve actual assets or explicitly seed a long-lived older browser cache.

    Args:
        filename: Exact data-free asset basename.
        request: Synthetic browser request with optional cache-fixture cookie.

    Returns:
        Current asset policy or an obsolete, deliberately cacheable test script.

    Raises:
        HTTPException: The path is not an explorer asset.
    """
    if filename not in LISTENING_ASSETS:
        raise HTTPException(404, "Unknown explorer asset.")
    legacy = request.cookies.get("legacy_assets") == "1"
    if legacy and not request.query_params.get("v") and filename in LEGACY_ASSETS:
        media = "text/css" if filename.endswith(".css") else "application/javascript"
        return Response(
            LEGACY_ASSETS[filename],
            media_type=media,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    return FileResponse(
        FRONTEND / "lastfm-assets" / filename,
        headers={"Cache-Control": listening_asset_cache_control(filename)},
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Provide the same public startup probe as the real web wrapper."""
    return {"status": "ok"}


@app.get("/auth/check")
def auth_check() -> dict[str, str]:
    """Let the real password middleware authenticate the browser fixture."""
    return {"status": "ok"}


@app.get("/lastfm")
def shell(request: Request) -> Response:
    """Serve the actual shell or a read-only cache-seeding fixture.

    Args:
        request: Browser request selecting the fixture explicitly.

    Returns:
        Revalidated data-free shell for current or deliberately older code.
    """
    if request.query_params.get("legacy") == "1":
        return Response(
            LEGACY_SHELL,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
    return FileResponse(FRONTEND / "lastfm.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8018)
