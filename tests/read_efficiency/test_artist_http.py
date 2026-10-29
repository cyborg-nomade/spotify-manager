"""Follow a real HTTP lookup through application rules and native read resources."""

from dataclasses import dataclass

import httpx
import pytest

from spotify_manager import api
from spotify_manager.bootstrap.execution import ExecutionRuntime
from spotify_manager.infrastructure.spotify_async.client import AsyncSpotify
from spotify_manager.infrastructure.spotify_async.retries import RetryProfile
from spotify_manager.interfaces.http.jobs import get_client
from tests.read_efficiency.catalog_memory import catalog_track
from tests.read_efficiency.catalog_memory import release_ids
from tests.read_efficiency.test_native_catalog import CatalogHttp
from tests.spotify_async.memory import transport_memory


def _artist_page(offset: int) -> dict[str, object]:
    items = []
    for identifier in release_ids(80)[offset : offset + 50]:
        items.append(catalog_track(identifier))
    return {"items": items, "next": "next-artist-page" if offset == 0 else None}


def _membership(request: httpx.Request) -> list[bool]:
    uris = request.url.params["uris"].split(",")
    divisor = 2 if uris[0].startswith("spotify:album:") else 3
    return [int(uri.rsplit(":", 1)[1]) % divisor == 0 for uri in uris]


@dataclass
class ArtistHttp(CatalogHttp):
    """Serve the real artist, cursor, metadata and membership endpoint contracts."""

    async def handle(self, request: httpx.Request) -> httpx.Response:
        """Overlap only album metadata; reject overlap at live membership reads.

        Args:
            request: Actual native endpoint request.

        Returns:
            Complete deterministic Spotify response.
        """
        if request.url.path == "/v1/albums/":
            return await super().handle(request)
        assert self.active == 0 and request.method == "GET"
        self.requests.append(request)
        if request.url.path == "/v1/artists/artist":
            return httpx.Response(200, json={"id": "artist", "name": "Artist"})
        if request.url.path == "/v1/artists/artist/albums":
            return httpx.Response(
                200, json=_artist_page(int(request.url.params["offset"]))
            )
        assert request.url.path == "/v1/me/library/contains"
        return httpx.Response(200, json=_membership(request))


@dataclass(frozen=True)
class NativeProvider:
    """Supply the native client through FastAPI's required callable provider API.

    Args:
        client: Same-loop native client backed by the synthetic HTTP resource.
    """

    client: AsyncSpotify

    def __call__(self) -> AsyncSpotify:
        """Return the existing native resource without creating or closing it.

        Returns:
            Caller-owned native client.
        """
        return self.client


async def _api_response() -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.app), base_url="http://testserver"
    ) as client:
        return await client.get("/artists/stats", params={"artist_id": "artist"})


async def _lookup(
    source: ArtistHttp, monkeypatch: pytest.MonkeyPatch
) -> httpx.Response:
    memory = transport_memory(http=source, profile=RetryProfile(0, 0, (999,)))
    provider = NativeProvider(AsyncSpotify(memory.transport))
    overrides = dict(api.app.dependency_overrides)
    overrides[get_client] = provider
    monkeypatch.setattr(api.app, "dependency_overrides", overrides)
    try:
        async with ExecutionRuntime() as runtime:
            monkeypatch.setattr(api.app.state, "execution", runtime, raising=False)
            return await _api_response()
    finally:
        await memory.transport.aclose()


async def test_http_artist_statistics_keep_membership_and_cursor_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify native catalog overlap through the real route, use case and presenter.

    Args:
        monkeypatch: Isolate native HTTP and the existing request resource owner.
    """
    source = ArtistHttp()
    response = await _lookup(source, monkeypatch)
    assert response.status_code == 200
    assert response.json() == {
        "artist_name": "Artist",
        "artist_id": "artist",
        "liked_tracks": 27,
        "saved_releases": 40,
        "source": "spotify-live",
    }
    assert len(source.requests) == 15 and source.peak == 4 and source.active == 0
    assert [request.url.params["offset"] for request in source.requests[1:3]] == [
        "0",
        "50",
    ]
    for request in source.requests[-4:]:
        assert request.url.path == "/v1/me/library/contains"


@pytest.mark.parametrize(
    "upstream, response_status", [(401, 502), (403, 403), (429, 429), (500, 502)]
)
async def test_native_lookup_errors_keep_the_public_http_contract(
    upstream: int, response_status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain error mapping while draining all admitted metadata reads.

    Args:
        upstream: Original Spotify status from the first catalog batch.
        response_status: Existing public HTTP translation.
        monkeypatch: Scoped native resource and provider substitutions.
    """
    source = ArtistHttp(status=upstream)
    response = await _lookup(source, monkeypatch)
    assert response.status_code == response_status
    assert "detail" in response.json()
    assert source.active == 0 and len(source.requests) == 11
    if upstream == 429:
        assert response.headers["Retry-After"] == "7"
