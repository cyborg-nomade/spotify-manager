"""Read exact Last.fm album thumbnails with a bounded archive fallback."""

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.domain.listening_cover_values import AlbumCoverMetadata
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.listening.cover_http import MAX_IMAGE_BYTES
from spotify_manager.infrastructure.listening.cover_http import MAX_JSON_BYTES
from spotify_manager.infrastructure.listening.cover_http import _content
from spotify_manager.infrastructure.listening.cover_image import lastfm_album_page
from spotify_manager.infrastructure.listening.cover_image import lastfm_artwork
from spotify_manager.infrastructure.listening.origin_source import USER_AGENT
from spotify_manager.infrastructure.listening.provider_retry import retry_after_seconds
from spotify_manager.infrastructure.listening.tag_source import API_URL
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


_IMAGE_HOSTS = {"lastfm-img.freetls.fastly.net", "lastfm.freetls.fastly.net"}
_PLACEHOLDER = "2a96cbd8b46e442fc41c2b86b821562f"


@dataclass(frozen=True)
class _LastFmRead:
    cover: CoverFetchResult | None = None
    pause: float = 0


def _image_url(album: dict[str, object]) -> str | None:
    images = album.get("image")
    if not isinstance(images, list):
        return None
    for item in images[:10]:
        if isinstance(item, dict) and item.get("size") == "large":
            value = item.get("#text")
            return _validated_image_url(value)
    return None


def _validated_image_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 256 or _PLACEHOLDER in value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme != "https" or parts.netloc not in _IMAGE_HOSTS:
        return None
    if parts.query or parts.fragment:
        return None
    if not re.fullmatch(r"/i/u/174s/[0-9a-f]{32}\.(png|jpe?g)", parts.path):
        return None
    return value


def _lookup_image(payload: object, selected: RankedEntity) -> str | None:
    if not isinstance(payload, dict) or not isinstance(
        album := payload.get("album"), dict
    ):
        return None
    artist, title = album.get("artist"), album.get("name")
    if not isinstance(artist, str) or not isinstance(title, str):
        return None
    if listening_identity((artist, title)) != selected.key:
        return None
    return _image_url(album)


def _cacheable(headers: httpx.Headers) -> bool:
    if headers.get("Content-Encoding", "identity").casefold() != "identity":
        return False
    control = headers.get("Cache-Control", "").casefold()
    if "no-store" in control or "no-cache" in control:
        return False
    age = re.search(r"\bmax-age\s*=\s*(\d{1,15})", control)
    return age is None or int(age[1]) >= 30 * 24 * 3600


def _read_image(client: httpx.Client, album: RankedEntity, url: str) -> _LastFmRead:
    with client.stream("GET", url) as response:
        if response.status_code != 200 or not _cacheable(response.headers):
            return _LastFmRead()
        content = _content(response, MAX_IMAGE_BYTES, time.monotonic() + 10)
    artwork, image = lastfm_artwork(
        content, lastfm_album_page(album.artist, album.name)
    )
    dated = datetime.now(UTC).isoformat()
    metadata = AlbumCoverMetadata(
        album.key, album.name, album.artist, "ready", (), 0, dated, artwork
    )
    return _LastFmRead(CoverFetchResult(metadata, image))


def _read_album(client: httpx.Client, album: RankedEntity, key: str) -> _LastFmRead:
    params = {
        "method": "album.getInfo",
        "api_key": key,
        "artist": album.artist,
        "album": album.name,
        "autocorrect": "0",
        "format": "json",
    }
    with client.stream("GET", API_URL, params=params) as response:
        if response.status_code == 429:
            return _LastFmRead(
                pause=max(60, retry_after_seconds(response.headers.get("Retry-After")))
            )
        if response.status_code != 200 or not _cacheable(response.headers):
            return _LastFmRead()
        content = _content(response, MAX_JSON_BYTES, time.monotonic() + 10)
    payload: object = json.loads(content)
    if isinstance(payload, dict) and payload.get("error") in (29, "29"):
        return _LastFmRead(pause=60)
    url = _lookup_image(payload, album)
    return _read_image(client, album, url) if url else _LastFmRead()


class LastFmCoverSource:
    """Read corroborated Last.fm thumbnails independently of the archive."""

    def __init__(self, api_key: str) -> None:
        """Bind the existing server-only key and initialize the provider pause."""
        self._key = api_key
        self._paused_until = 0.0

    def _read(self, album: RankedEntity) -> _LastFmRead:
        try:
            headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
            with httpx.Client(
                timeout=5, follow_redirects=False, headers=headers
            ) as client:
                return _read_album(client, album, self._key)
        except httpx.TransportError, OSError:
            return _LastFmRead(pause=30)
        except httpx.HTTPError, httpx.InvalidURL, ValueError, CoverSourceError:
            return _LastFmRead()

    async def fetch(self, album: RankedEntity) -> CoverFetchResult | None:
        """Return a usable Last.fm thumbnail or defer this album to the next pass.

        Args:
            album: Selected history title and complete credited artist.

        Returns:
            Exact Last.fm cover evidence, or none if unavailable.
        """
        if self._key and time.monotonic() >= self._paused_until:
            async with blocking_capacity():
                task = asyncio.create_task(asyncio.to_thread(self._read, album))
                result = await finish_blocking(task)
            if result.cover is not None:
                return result.cover
            if result.pause:
                self._paused_until = time.monotonic() + result.pause
        return None
