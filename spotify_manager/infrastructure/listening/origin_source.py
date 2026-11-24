"""Bounded MusicBrainz exact-name evidence with process-wide request spacing."""

import asyncio
import json
import re
from datetime import UTC
from datetime import datetime
from http.client import RemoteDisconnected
from ssl import SSLError
from typing import cast
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen
from uuid import UUID

from spotify_manager.application.listening_origin_ports import OriginSourceError
from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_origin_values import OriginCandidate
from spotify_manager.domain.listening_origin_values import OriginState
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity
from spotify_manager.infrastructure.async_work import blocking_capacity
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    MusicBrainzRequestGate,
)
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    ProviderCooldownError,
)
from spotify_manager.infrastructure.listening.provider_retry import RETRYABLE_STATUSES
from spotify_manager.infrastructure.listening.provider_retry import retry_after_seconds
from spotify_manager.infrastructure.listening.provider_retry import retry_stop_message
from spotify_manager.infrastructure.spotify_async.blocking import finish_blocking


API_URL = "https://musicbrainz.org/ws/2/artist/"
USER_AGENT = "spotify-manager/0.1.0 (https://github.com/cyborg-nomade/spotify-manager)"
MAX_RESPONSE_BYTES = 1048576


def _text(raw: dict[str, object], name: str) -> str:
    value = raw.get(name, "")
    if not isinstance(value, str) or len(value) > 1000:
        raise OriginSourceError("Public artist field was invalid.")
    return value.strip()


def _codes(raw: dict[str, object], area: dict[str, object]) -> tuple[str, ...]:
    country = _text(raw, "country")
    values = area.get("iso-3166-1-codes", [])
    if not isinstance(values, list) or len(values) > 10:
        raise OriginSourceError("Public country codes were invalid.")
    result = set()
    for code in [country, *values]:
        if not isinstance(code, str) or (code and not re.fullmatch(r"[A-Z]{2}", code)):
            raise OriginSourceError("Public country code was invalid.")
        if code:
            result.add(code)
    return tuple(sorted(result))


def _place(raw: dict[str, object], name: str) -> dict[str, object]:
    place = raw.get(name)
    if place is None:
        return {}
    if not isinstance(place, dict):
        raise OriginSourceError("Public artist place was invalid.")
    return cast(dict[str, object], place)


def origin_candidate(raw: dict[str, object]) -> OriginCandidate:
    """Validate one provider candidate while retaining its own disambiguation.

    Args:
        raw: One external artist object.

    Returns:
        Safe, bounded candidate fields with a canonical provider identity.

    Raises:
        OriginSourceError: An identity, label or country field is malformed.
    """
    mbid = _text(raw, "id")
    try:
        valid = str(UUID(mbid)) == mbid
    except ValueError:
        valid = False
    if not valid:
        raise OriginSourceError("Public artist identity was invalid.")
    area = _place(raw, "area")
    return OriginCandidate(
        mbid,
        _text(raw, "name"),
        _text(raw, "disambiguation"),
        _text(raw, "type"),
        _text(area, "name"),
        _text(_place(raw, "begin-area"), "name"),
        _codes(raw, area),
    )


def _matches(rows: list[object], artist: RankedEntity) -> tuple[OriginCandidate, ...]:
    result: dict[str, OriginCandidate] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise OriginSourceError("Public artist row was invalid.")
        raw = cast(dict[str, object], row)
        if listening_identity((_text(raw, "name"),)) != artist.key:
            continue
        candidate = origin_candidate(raw)
        existing = result.get(candidate.mbid)
        if existing is not None and existing != candidate:
            raise OriginSourceError("Public candidate evidence conflicted.")
        result.setdefault(candidate.mbid, candidate)
    return tuple(result[key] for key in sorted(result))


def parse_artist_origins(
    payload: dict[str, object], artist: RankedEntity
) -> ArtistOriginMetadata:
    """Keep ambiguous or incomplete searches out of geographic totals.

    Args:
        payload: External MusicBrainz JSON search object.
        artist: Original requested history spelling and normalized identity.

    Returns:
        Dated exact-name candidates; a unique name never verifies identity.

    Raises:
        OriginSourceError: The provider response is malformed or an error.
    """
    count, rows = payload.get("count"), payload.get("artists")
    if type(count) is not int or not isinstance(rows, list):
        raise OriginSourceError("Public artist search was unavailable or invalid.")
    if count < 0 or len(rows) > 100 or count < len(rows):
        raise OriginSourceError("Public artist search bounds were invalid.")
    candidates = _matches(rows, artist)
    state: OriginState = "matched" if len(candidates) == 1 else "unmatched"
    if len(candidates) > 1:
        state = "ambiguous"
    if count > len(rows):
        state = "incomplete"
    return ArtistOriginMetadata(
        artist.key,
        artist.name,
        state,
        candidates[:5],
        len(candidates),
        datetime.now(UTC).isoformat(),
    )


def _payload(request: Request) -> dict[str, object]:
    try:
        with urlopen(request, timeout=15) as response:
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        retry_after = error.headers.get("Retry-After") if error.headers else None
        raise OriginSourceError(
            "Public MusicBrainz search was unavailable.",
            temporary=error.code in RETRYABLE_STATUSES,
            retry_after=retry_after_seconds(retry_after),
        ) from None
    except URLError as error:
        raise OriginSourceError(
            "Public MusicBrainz search could not connect.",
            temporary=isinstance(error.reason, OSError)
            and not isinstance(error.reason, SSLError),
        ) from None
    except TimeoutError, ConnectionError, RemoteDisconnected:
        raise OriginSourceError(
            "Public MusicBrainz search could not connect.", temporary=True
        ) from None
    except OSError:
        raise OriginSourceError(
            "Public MusicBrainz search could not connect."
        ) from None
    if len(content) > MAX_RESPONSE_BYTES:
        raise OriginSourceError("Public artist search exceeded its size limit.")
    try:
        raw: object = json.loads(content)
    except ValueError, UnicodeError:
        raise OriginSourceError("Public artist search was not valid JSON.") from None
    if not isinstance(raw, dict):
        raise OriginSourceError("Public artist search was not an object.")
    return cast(dict[str, object], raw)


class MusicBrainzOriginSource:
    """Own fixed public searches; no account, history or location is submitted."""

    def __init__(self, gate: MusicBrainzRequestGate | None = None) -> None:
        """Bind a shared provider gate, or own one for a standalone resource.

        Args:
            gate: Application-owned limiter shared with album-cover searches.
        """
        self._gate = gate or MusicBrainzRequestGate()

    @property
    def configured(self) -> bool:
        """Return public availability configuration; this provider needs no key."""
        return True

    def read(self, artist: RankedEntity) -> ArtistOriginMetadata:
        """Perform one bounded exact-name search without implicit retry.

        Args:
            artist: Captured display name and history identity.

        Returns:
            Current country-association candidates with explicit search coverage.

        Raises:
            OriginSourceError: Provider, transport or response failure.
        """
        escaped = re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", artist.name)
        query = {"query": 'artistaccent:"' + escaped + '"', "fmt": "json", "limit": 100}
        request = Request(
            API_URL + "?" + urlencode(query), headers={"User-Agent": USER_AGENT}
        )
        return parse_artist_origins(_payload(request), artist)

    async def fetch(self, artist: RankedEntity) -> ArtistOriginMetadata:
        """Retry temporary reads through the shared request gate.

        Args:
            artist: Captured artist name; no listening records are transmitted.

        Returns:
            Complete provider observation.

        Raises:
            OriginSourceError: The concrete provider read failed.
        """
        attempt = 1
        waited = 0.0
        while True:
            try:
                return await self._attempt(artist)
            except ProviderCooldownError:
                raise OriginSourceError(
                    "MusicBrainz requested a longer pause. Try again later."
                ) from None
            except OriginSourceError as error:
                if not error.temporary:
                    raise
                delay = self._gate.schedule_retry(error, attempt, waited)
                if delay is None:
                    raise OriginSourceError(
                        retry_stop_message(error.retry_after)
                    ) from None
            waited += delay
            attempt += 1

    async def _attempt(self, artist: RankedEntity) -> ArtistOriginMetadata:
        async with self._gate, blocking_capacity():
            worker = asyncio.create_task(asyncio.to_thread(self.read, artist))
            return await finish_blocking(worker)
