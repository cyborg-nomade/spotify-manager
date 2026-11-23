"""Explicit exact album searches and representative Cover Art Archive thumbnails."""

import asyncio
import re
from dataclasses import replace
from urllib.parse import urlencode
from urllib.parse import urlsplit

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.domain.listening_cover_values import AlbumCoverMetadata
from spotify_manager.domain.listening_cover_values import CoverFetchResult
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.listening.cover_http import MAX_IMAGE_BYTES
from spotify_manager.infrastructure.listening.cover_http import CoverHttpReads
from spotify_manager.infrastructure.listening.cover_image import cover_artwork
from spotify_manager.infrastructure.listening.cover_image import validate_cover_image
from spotify_manager.infrastructure.listening.cover_search import cover_mbid
from spotify_manager.infrastructure.listening.cover_search import parse_cover_search
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    MusicBrainzRequestGate,
)
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    ProviderCooldownError,
)
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


def _phrase(value: str) -> str:
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", value)


def _front(payload: dict[str, object]) -> tuple[str, str] | None:
    release = payload.get("release")
    if not isinstance(release, str):
        raise CoverSourceError("Public artwork release was invalid.")
    try:
        parts = urlsplit(release)
    except ValueError:
        raise CoverSourceError("Public artwork release was invalid.") from None
    if (
        parts.scheme not in {"http", "https"}
        or parts.netloc != "musicbrainz.org"
        or not parts.path.startswith("/release/")
        or parts.query
        or parts.fragment
    ):
        raise CoverSourceError("Public artwork release was invalid.")
    mbid = cover_mbid(parts.path.removeprefix("/release/"))
    images = payload.get("images")
    if not isinstance(images, list) or len(images) > 100:
        raise CoverSourceError("Public artwork list was invalid.")
    for image in images:
        if not isinstance(image, dict):
            raise CoverSourceError("Public artwork entry was invalid.")
        if image.get("front") is True and image.get("approved") is True:
            return mbid, _image_id(image.get("id"))
    return None


def _image_id(value: object) -> str:
    if type(value) is int:
        value = str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,30}", value):
        return value
    raise CoverSourceError("Public artwork identity was invalid.")


class MusicBrainzCoverSource:
    """Own public name searches and bounded, validated representative artwork.

    Args:
        gate: Application-owned MusicBrainz limiter shared with Artist Atlas.
        reads: Named fixed-provider HTTP resource.
    """

    def __init__(self, gate: MusicBrainzRequestGate, reads: CoverHttpReads) -> None:
        """Bind provider resources without reading private names or remote data.

        Args:
            gate: Shared sequential request-start gate.
            reads: Bounded public metadata and thumbnail resource.
        """
        self._gate = gate
        self._reads = reads

    @property
    def configured(self) -> bool:
        """Return public availability configuration; no account or key is required.

        Returns:
            True for the fixed public source.
        """
        return True

    def read(self, album: RankedEntity) -> CoverFetchResult:
        """Resolve complete title/credit evidence before requesting any artwork.

        Args:
            album: Captured original title and artist; counts are not transmitted.

        Returns:
            Complete evidence and optional validated representative JPEG.

        Raises:
            CoverSourceError: Provider, metadata or image failure.
        """
        query = (
            'releasegroupaccent:"'
            + _phrase(album.name)
            + '" AND artist:"'
            + _phrase(album.artist)
            + '"'
        )
        url = "https://musicbrainz.org/ws/2/release-group/?" + urlencode(
            {"query": query, "fmt": "json", "limit": 100}
        )
        payload = self._reads.read_json(url)
        if payload is None:
            raise CoverSourceError("Public album search was unavailable.")
        metadata = parse_cover_search(payload, album)
        if metadata.state != "no_cover":
            return CoverFetchResult(metadata)
        return self._artwork(metadata)

    def _artwork(self, metadata: AlbumCoverMetadata) -> CoverFetchResult:
        group = metadata.candidates[0].mbid
        payload = self._reads.read_json(
            "https://coverartarchive.org/release-group/" + group
        )
        source = _front(payload) if payload is not None else None
        if source is None:
            return CoverFetchResult(metadata)
        release, image_id = source
        url = f"https://coverartarchive.org/release/{release}/{image_id}-250.jpg"
        content = self._reads.read_bytes(url, MAX_IMAGE_BYTES)
        if content is None:
            return CoverFetchResult(metadata)
        image = validate_cover_image(content)
        artwork = cover_artwork(image, release, image_id)
        return CoverFetchResult(
            replace(metadata, state="ready", artwork=artwork), image
        )

    async def fetch(self, album: RankedEntity) -> CoverFetchResult:
        """Retry temporary reads through the shared request gate.

        Args:
            album: Captured title and artist from the visible ranked quilt.

        Returns:
            Completed provider observation and optional bounded image bytes.

        Raises:
            CoverSourceError: A safe provider or image-validation failure.
        """
        attempt = 1
        while True:
            try:
                return await self._attempt(album)
            except ProviderCooldownError:
                raise CoverSourceError(
                    "A metadata provider requested a longer pause. Try again later."
                ) from None
            except CoverSourceError as error:
                if not self._gate.schedule_retry(error, attempt):
                    raise
            attempt += 1

    async def _attempt(self, album: RankedEntity) -> CoverFetchResult:
        async with self._gate, blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.read, album))
            return await finish_blocking(worker)
