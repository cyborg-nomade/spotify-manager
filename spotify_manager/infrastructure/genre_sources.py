"""Decode Every Noise links, Spotify embed markers and the preserved route asset."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import cast

from pydantic import ValidationError

from spotify_manager.application.genre_values import GenreRevealSourceError
from spotify_manager.application.genre_values import GenreRevealStateError
from spotify_manager.domain.genres import GenreRouteEntry
from spotify_manager.infrastructure.genre_models import GenreRevealRunRequest


SPOTIFY_PLAYLIST_URL_PATTERN = re.compile(
    r"^https://open\.spotify\.com/(?:user/[^/]+/)?playlist/"
    r"(?P<id>[A-Za-z0-9]+)(?:[/?#].*)?$"
)


class EveryNoisePlaylistParser(HTMLParser):
    """Collect playlist anchors and labels in original document order."""

    def __init__(self) -> None:
        """Initialize a source parser without reading a page."""
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Keep only valid Spotify playlist anchors.

        Args:
            tag: Original HTML tag.
            attrs: Original ordered attribute pairs.
        """
        if tag.casefold() != "a":
            return
        attributes = dict(attrs)
        href = attributes.get("href") or ""
        title = attributes.get("title") or ""
        if SPOTIFY_PLAYLIST_URL_PATTERN.fullmatch(href):
            self.links.append((href, title))


def primary_playlist(links: list[tuple[str, str]], name: str) -> str:
    """Select the first primary sound-of-genre playlist, ignoring intro/pulse links.

    Args:
        links: Validated playlist anchors in original document order.
        name: Original genre display name used in errors.

    Returns:
        Original first primary playlist URL.

    Raises:
        GenreRevealSourceError: No primary source link was discovered.
    """
    for href, title in links:
        if title.casefold().startswith(
            "listen to the sound of "
        ) and title.casefold().endswith(" on spotify"):
            return href
    raise GenreRevealSourceError(
        f"Every Noise has no primary Spotify playlist for {name}."
    )


def first_track_uris(
    html: str, pattern: re.Pattern[str], count: int
) -> tuple[str, ...]:
    """Retain the first distinct original public-embed markers.

    Args:
        html: Original public Spotify embed response.
        pattern: Original track-URI recognizer.
        count: Original required number of distinct source markers.

    Returns:
        Required distinct markers in original occurrence order.

    Raises:
        GenreRevealSourceError: The page exposes fewer than the required markers.
    """
    track_uris = tuple(dict.fromkeys(pattern.findall(html)))
    if len(track_uris) < count:
        raise GenreRevealSourceError(
            f"Spotify's public playlist page did not expose the first {count} tracks."
        )
    return track_uris[:count]


def _route_entry(raw: object, position: int) -> GenreRouteEntry:
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError
    request = GenreRevealRunRequest(name=str(raw[0]), slug=str(raw[1]))
    return GenreRouteEntry(request.name, request.slug, position)


def decode_route(
    html: str, path: Path, pattern: re.Pattern[str], maximum: int
) -> tuple[GenreRouteEntry, ...]:
    """Decode the original standalone HTML route without sorting or deduplication.

    Args:
        html: Original route asset text.
        path: Original route location used in errors.
        pattern: Original route-data recognizer.
        maximum: Original maximum number of route entries.

    Returns:
        Validated original route entries in their preserved order.

    Raises:
        GenreRevealStateError: Route data is absent or has invalid syntax or entries.
    """
    match = pattern.search(html)
    if match is None:
        raise GenreRevealStateError(f"Genre route data was not found in {path}.")
    try:
        raw = json.loads(match.group("route"))
    except json.JSONDecodeError as exc:
        raise GenreRevealStateError(f"Genre route data is invalid in {path}.") from exc
    if not isinstance(raw, list) or len(raw) > maximum:
        raise GenreRevealStateError(f"Genre route data is invalid in {path}.")
    entries: list[GenreRouteEntry] = []
    try:
        for position, entry in enumerate(cast(list[object], raw), start=1):
            entries.append(_route_entry(entry, position))
    except (TypeError, ValueError, ValidationError) as exc:
        raise GenreRevealStateError(f"Genre route data is invalid in {path}.") from exc
    return tuple(entries)
