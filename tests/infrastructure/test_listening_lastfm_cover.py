"""Verify exact Last.fm thumbnails and bounded fallback without public calls."""

from dataclasses import dataclass
from dataclasses import field
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image

from spotify_manager.domain.listening_cover_values import LastFmArtwork
from spotify_manager.infrastructure.listening import lastfm_cover
from spotify_manager.infrastructure.listening.cover_cache import AlbumCoverCache
from spotify_manager.infrastructure.listening.lastfm_cover import LastFmCoverSource
from tests.support.listening_covers import album


_CDN_URL = "https://lastfm-img.freetls.fastly.net/i/u/174s/" + "a" * 32 + ".png"


def _png() -> bytes:
    output = BytesIO()
    with Image.new("RGB", (174, 174), "#698e8c") as image:
        image.save(output, format="PNG")
    return output.getvalue()


@dataclass
class LastFmResponses:
    """Provide deterministic metadata and thumbnail responses to the real client."""

    responses: list[httpx.Response]
    sent: list[httpx.Request] = field(default_factory=list)

    def respond(self, request: httpx.Request) -> httpx.Response:
        """Record a request and return the next expected response."""
        self.sent.append(request)
        return self.responses.pop(0)


def _source(
    monkeypatch: pytest.MonkeyPatch, responses: LastFmResponses
) -> LastFmCoverSource:
    client = httpx.Client(transport=httpx.MockTransport(responses.respond))
    monkeypatch.setattr(lastfm_cover.httpx, "Client", lambda **_: client)
    return LastFmCoverSource("test-api-key")


def _album(artist: str, image_url: str = _CDN_URL) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "album": {
                "artist": artist,
                "name": "Record",
                "image": [{"size": "large", "#text": image_url}],
            }
        },
    )


@pytest.mark.asyncio
async def test_exact_lastfm_png_round_trips_without_the_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use the verified Last.fm bytes, strip credentials and retain attribution."""
    png = _png()
    responses = LastFmResponses([_album("ALPHA"), httpx.Response(200, content=png)])
    source = _source(monkeypatch, responses)
    result = await source.fetch(album())
    assert result is not None
    artwork = result.metadata.artwork
    assert isinstance(artwork, LastFmArtwork)
    assert artwork.page_url == "https://www.last.fm/music/Alpha/Record"
    api, image = responses.sent
    assert api.url.params["api_key"] == "test-api-key"
    assert api.url.params["autocorrect"] == "0"
    assert str(image.url) == _CDN_URL
    assert "test-api-key" not in str(image.headers)
    assert result.image is not None and result.image.content == png
    AlbumCoverCache(tmp_path).write(result)
    restored = AlbumCoverCache(tmp_path).current()
    assert restored.entries == (result.metadata,)
    assert restored.images[0].content == png


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "artist,image",
    [("Wrong Artist", _CDN_URL), ("Alpha", "https://other.invalid/i/u/174s/test.png")],
)
async def test_mismatched_metadata_or_host_falls_back_without_fetching_image(
    monkeypatch: pytest.MonkeyPatch, artist: str, image: str
) -> None:
    """Reject weak identity evidence and refuse uncontrolled image destinations."""
    responses = LastFmResponses([_album(artist, image)])
    source = _source(monkeypatch, responses)
    result = await source.fetch(album())
    assert result is None
    assert len(responses.sent) == 1


@pytest.mark.asyncio
async def test_lastfm_rate_limit_skips_retries_and_uses_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One throttled public response leaves subsequent covers free to fall back."""
    responses = LastFmResponses([httpx.Response(429, headers={"Retry-After": "30"})])
    source = _source(monkeypatch, responses)
    assert await source.fetch(album()) is None
    assert await source.fetch(album("Second")) is None
    assert len(responses.sent) == 1
