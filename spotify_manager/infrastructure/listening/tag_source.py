"""Bounded public Last.fm tag reads with credential-free cached provenance."""

import asyncio
import json
from datetime import UTC
from datetime import datetime
from typing import cast
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from spotify_manager.application.listening_tag_ports import TagSourceError
from spotify_manager.domain.listening_tag_values import ArtistTagMetadata
from spotify_manager.domain.listening_tag_values import CommunityTag
from spotify_manager.domain.listening_tag_values import TagState
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


API_URL = "https://ws.audioscrobbler.com/2.0/"
MAX_RESPONSE_BYTES = 1048576


def _read_payload(request: Request) -> dict[str, object]:
    try:
        with urlopen(request, timeout=15) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError, URLError, TimeoutError, OSError:
        raise TagSourceError("Public Last.fm tag lookup could not connect.") from None
    if len(content) > MAX_RESPONSE_BYTES:
        raise TagSourceError("Public tag response exceeded its size limit.")
    try:
        raw: object = json.loads(content)
    except ValueError, UnicodeError:
        raise TagSourceError("Public tag response was not valid JSON.") from None
    if not isinstance(raw, dict):
        raise TagSourceError("Public tag response was not an object.")
    return cast(dict[str, object], raw)


def _tag(raw: object) -> CommunityTag:
    if not isinstance(raw, dict):
        raise TagSourceError("Public tag row was invalid.")
    name = raw.get("name")
    if not isinstance(name, str) or not 0 < len(name.strip()) <= 200:
        raise TagSourceError("Public tag label was invalid.")
    return CommunityTag(listening_identity((name,)), name.strip())


def _tags(raw: object) -> tuple[CommunityTag, ...]:
    if not isinstance(raw, list):
        raise TagSourceError("Public artist tags were not a list.")
    result: dict[str, CommunityTag] = {}
    for row in raw[:100]:
        tag = _tag(row)
        result.setdefault(tag.key, tag)
        if len(result) == 10:
            break
    return tuple(result.values())


def _observation(
    artist: RankedEntity, resolved: str, tags: tuple[CommunityTag, ...]
) -> ArtistTagMetadata:
    matched = listening_identity((resolved,)) == artist.key
    state: TagState = "tagged" if tags else "empty"
    if not matched:
        state, tags = "unresolved", ()
    url = "https://www.last.fm/music/" + quote(artist.name, safe="") + "/+tags"
    return ArtistTagMetadata(
        artist.key,
        artist.name,
        resolved,
        state,
        tags,
        datetime.now(UTC).isoformat(),
        url,
    )


def parse_artist_tags(
    payload: dict[str, object], artist: RankedEntity
) -> ArtistTagMetadata:
    """Accept only public tags corroborated by the requested artist identity.

    Args:
        payload: External JSON object, including possible HTTP-200 API errors.
        artist: Requested analytics identity and original display name.

    Returns:
        Ranked unique tags, verified empty tags, or unresolved identity.

    Raises:
        TagSourceError: The provider is unavailable or its response is malformed.
    """
    if payload.get("error") in (6, "6"):
        return _observation(artist, "", ())
    if "error" in payload:
        raise TagSourceError("Public Last.fm tag lookup is unavailable. Retry later.")
    container = payload.get("toptags")
    if not isinstance(container, dict):
        raise TagSourceError("Public tag response was missing artist metadata.")
    attributes = container.get("@attr")
    resolved = attributes.get("artist") if isinstance(attributes, dict) else None
    if not isinstance(resolved, str):
        raise TagSourceError("Public tag response did not identify its artist.")
    return _observation(artist, resolved, _tags(container.get("tag")))


class LastFmTagSource:
    """Own one configured, bounded public read endpoint without account mutation.

    Args:
        api_key: Existing optional Last.fm API credential, never cached or logged.
    """

    def __init__(self, api_key: str | None) -> None:
        """Bind only the configured public read credential.

        Args:
            api_key: Optional existing application setting.
        """
        self._api_key = api_key.strip() if api_key else ""

    @property
    def configured(self) -> bool:
        """Return whether explicit public lookups are configured.

        Returns:
            Whether an API key is present, without exposing it.
        """
        return bool(self._api_key)

    def read(self, artist: RankedEntity) -> ArtistTagMetadata:
        """Execute one fixed provider read with autocorrection disabled.

        Args:
            artist: Captured requested name and analytics identity.

        Returns:
            Identity-checked dated public metadata.

        Raises:
            TagSourceError: Configuration, provider or response failure.
        """
        if not self.configured:
            raise TagSourceError("Public Last.fm tag lookup is not configured.")
        parameters = {
            "method": "artist.getTopTags",
            "artist": artist.name,
            "api_key": self._api_key,
            "format": "json",
            "autocorrect": 0,
        }
        request = Request(
            API_URL + "?" + urlencode(parameters),
            headers={"User-Agent": "spotify-manager/0.1.0 (Listening Explorer)"},
        )
        return parse_artist_tags(_read_payload(request), artist)

    async def fetch(self, artist: RankedEntity) -> ArtistTagMetadata:
        """Run the fixed blocking provider read under bounded, drained ownership.

        Args:
            artist: Captured name and identity for one public read.

        Returns:
            Complete provider observation after the worker finishes.

        Raises:
            TagSourceError: The concrete read failed.
        """
        async with blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.read, artist))
            return await finish_blocking(worker)
