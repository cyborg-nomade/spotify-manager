"""Parse complete exact album-title and complete artist-credit search evidence."""

from datetime import UTC
from datetime import datetime
from typing import cast
from uuid import UUID

from spotify_manager.application.listening_cover_ports import CoverSourceError
from spotify_manager.domain.listening_cover_values import AlbumCoverMetadata
from spotify_manager.domain.listening_cover_values import CoverCandidate
from spotify_manager.domain.listening_cover_values import CoverState
from spotify_manager.domain.listening_time import listening_identity
from spotify_manager.domain.listening_values import RankedEntity


def cover_text(raw: dict[str, object], name: str) -> str:
    """Validate bounded provider text, treating absent optional fields as empty.

    Args:
        raw: External JSON object.
        name: Fixed property name.

    Returns:
        Trimmed text, preserving accents and punctuation.

    Raises:
        CoverSourceError: The field is not bounded text.
    """
    value = raw.get(name)
    if value is None:
        value = ""
    return _bounded_text(value).strip()


def _bounded_text(value: object) -> str:
    if not isinstance(value, str) or len(value) > 1000:
        raise CoverSourceError("Public album field was invalid.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise CoverSourceError("Public album text encoding was invalid.") from None
    return value


def cover_mbid(value: str) -> str:
    """Require one canonical provider UUID.

    Args:
        value: External provider identifier.

    Returns:
        The unchanged canonical identity.

    Raises:
        CoverSourceError: Identity is not a canonical UUID.
    """
    try:
        if str(UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise CoverSourceError("Public album identity was invalid.")


def _credit(raw: dict[str, object]) -> str:
    names = raw.get("artist-credit")
    if not isinstance(names, list) or not 1 <= len(names) <= 20:
        raise CoverSourceError("Public album artist credit was invalid.")
    result = []
    for credit in names:
        if not isinstance(credit, dict) or not isinstance(credit.get("artist"), dict):
            raise CoverSourceError("Public album artist credit was invalid.")
        name = credit.get("name")
        if name is None:
            name = credit["artist"].get("name")
        join = credit.get("joinphrase", "")
        if not isinstance(name, str) or not name.strip() or not isinstance(join, str):
            raise CoverSourceError("Public album artist credit was invalid.")
        result.append(name + join)
    value = "".join(result).strip()
    return _bounded_text(value)


def _candidate(raw: dict[str, object]) -> CoverCandidate:
    title = cover_text(raw, "title")
    if not title:
        raise CoverSourceError("Public album title was missing.")
    return CoverCandidate(
        cover_mbid(cover_text(raw, "id")),
        title,
        _credit(raw),
        cover_text(raw, "disambiguation"),
    )


def _matches(rows: list[object], album: RankedEntity) -> tuple[CoverCandidate, ...]:
    result: dict[str, CoverCandidate] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CoverSourceError("Public album search row was invalid.")
        candidate = _candidate(cast(dict[str, object], row))
        if listening_identity((candidate.artist, candidate.title)) != album.key:
            continue
        previous = result.get(candidate.mbid)
        if previous is not None and previous != candidate:
            raise CoverSourceError("Public album evidence conflicted.")
        result[candidate.mbid] = candidate
    return tuple(result[key] for key in sorted(result))


def parse_cover_search(
    payload: dict[str, object], album: RankedEntity
) -> AlbumCoverMetadata:
    """Retain exact-name candidates without choosing by score or removing editions.

    Args:
        payload: Bounded MusicBrainz release-group search response.
        album: Requested original title/artist and history identity.

    Returns:
        Dated search evidence; a unique candidate still needs an artwork lookup.

    Raises:
        CoverSourceError: Invalid counts, identities, fields or duplicate evidence.
    """
    count, rows = payload.get("count"), payload.get("release-groups")
    if type(count) is not int or not isinstance(rows, list):
        raise CoverSourceError("Public album search was unavailable or invalid.")
    if count < 0 or len(rows) > 100 or count < len(rows):
        raise CoverSourceError("Public album search bounds were invalid.")
    candidates = _matches(rows, album)
    state: CoverState = "no_cover" if len(candidates) == 1 else "unmatched"
    if len(candidates) > 1:
        state = "ambiguous"
    if count > len(rows):
        state = "incomplete"
    return AlbumCoverMetadata(
        album.key,
        album.name,
        album.artist,
        state,
        candidates[:5],
        len(candidates),
        datetime.now(UTC).isoformat(),
    )
