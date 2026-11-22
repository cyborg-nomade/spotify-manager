"""Bounded public metadata/image reads with validated HTTPS redirect destinations."""

import json
import time
from typing import cast
from urllib.parse import urljoin
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import httpx

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.infrastructure.listening.origin_source import USER_AGENT


MAX_IMAGE_BYTES = 131072
MAX_JSON_BYTES = 1048576


def public_cover_url(url: str) -> str:
    """Validate and upgrade only fixed public music/archive provider hosts.

    Args:
        url: Provider URL, possibly a documented HTTP archive redirect.

    Returns:
        HTTPS URL without credentials or nonstandard ports.

    Raises:
        CoverSourceError: The destination is outside the supported public hosts.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        valid = host in {
            "musicbrainz.org",
            "coverartarchive.org",
            "archive.org",
        } or host.endswith(".archive.org")
        if (
            parts.scheme not in {"http", "https"}
            or not valid
            or parts.username
            or parts.password
            or parts.port not in {None, 80, 443}
        ):
            raise ValueError("Unsupported destination.")
    except ValueError:
        raise CoverSourceError("Artwork destination was not supported.") from None
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def _content(response: httpx.Response, limit: int, deadline: float) -> bytes:
    content = bytearray()
    for part in response.iter_bytes():
        _check_budget(deadline)
        if len(content) + len(part) > limit:
            raise CoverSourceError("Public artwork response exceeded its size limit.")
        content.extend(part)
    return bytes(content)


def _check_budget(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise CoverSourceError("Public artwork response exceeded its time budget.")


class CoverHttpReads:
    """Read public provider responses without application credentials or retries."""

    def read_bytes(self, url: str, limit: int) -> bytes | None:
        """Follow at most four validated redirects and bound decompressed bytes.

        Args:
            url: Fixed provider URL built from escaped names or validated IDs.
            limit: Maximum retained decompressed response bytes.

        Returns:
            Complete bytes, or no content for an explicit HTTP 404.

        Raises:
            CoverSourceError: Transport, destination, status or size failure.
        """
        target = public_cover_url(url)
        try:
            with httpx.Client(timeout=15, follow_redirects=False) as client:
                return self._read(client, target, limit)
        except httpx.HTTPError, httpx.InvalidURL, OSError:
            raise CoverSourceError(
                "Public artwork service could not connect."
            ) from None

    def _read(self, client: httpx.Client, target: str, limit: int) -> bytes | None:
        deadline = time.monotonic() + 30
        for _ in range(5):
            _check_budget(deadline)
            result = self._one(client, target, limit, deadline)
            if not isinstance(result, str):
                return result
            target = public_cover_url(urljoin(target, result))
        raise CoverSourceError("Public artwork service redirected too many times.")

    def _one(
        self, client: httpx.Client, target: str, limit: int, deadline: float
    ) -> bytes | str | None:
        with client.stream(
            "GET",
            target,
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        ) as response:
            return self._response(response, limit, deadline)

    def _response(
        self, response: httpx.Response, limit: int, deadline: float
    ) -> bytes | str | None:
        if response.status_code == 404:
            return None
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            if not location:
                raise CoverSourceError("Public artwork redirect was invalid.")
            return location
        if response.status_code != 200:
            raise CoverSourceError("Public artwork service is unavailable.")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise CoverSourceError("Public artwork encoding was unsupported.")
        return _content(response, limit, deadline)

    def read_json(self, url: str) -> dict[str, object] | None:
        """Decode a complete bounded JSON document, preserving explicit absence.

        Args:
            url: Validated public metadata endpoint.

        Returns:
            One JSON object, or explicit provider 404.

        Raises:
            CoverSourceError: A malformed, oversized or unavailable response.
        """
        content = self.read_bytes(url, MAX_JSON_BYTES)
        if content is None:
            return None
        try:
            value: object = json.loads(content)
        except ValueError, UnicodeError:
            raise CoverSourceError(
                "Public artwork metadata was not valid JSON."
            ) from None
        if not isinstance(value, dict):
            raise CoverSourceError("Public artwork metadata was not an object.")
        return cast(dict[str, object], value)
