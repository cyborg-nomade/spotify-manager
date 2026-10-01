"""Ordered genre routes and identity-based destination selection."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GenreRouteEntry:
    """One preserved nearest-neighbour genre route entry.

    Args:
        name: Original display name.
        slug: Original Every Noise genre identity.
        position: Original one-based route position.
    """

    name: str
    slug: str
    position: int


@dataclass(frozen=True)
class GenreSource:
    """Observed public links for a validated genre.

    Args:
        slug: Original genre identity.
        name: Original display name.
        every_noise_url: Original public genre page.
        source_playlist_id: Discovered primary playlist identity.
        source_playlist_uri: Discovered primary playlist URI.
        source_playlist_url: Original canonical public playlist link.
    """

    slug: str
    name: str
    every_noise_url: str
    source_playlist_id: str
    source_playlist_uri: str
    source_playlist_url: str


@dataclass(frozen=True)
class GenrePlaylistSource:
    """Discovered source and its original ordered track markers.

    Args:
        preview: Original public source metadata.
        track_uris: Original ordered source markers.
    """

    preview: GenreSource
    track_uris: tuple[str, ...]


def first_incomplete(
    route: tuple[GenreRouteEntry, ...], completed: set[str]
) -> GenreRouteEntry | None:
    """Find the first unfinished genre in the preserved route order.

    Args:
        route: Original ordered route.
        completed: Original completed identities.

    Returns:
        First unfinished entry, or no entry when the route is complete.
    """
    for entry in route:
        if entry.slug not in completed:
            return entry
    return None


def destination_tracks(
    source: tuple[str, ...], existing: frozenset[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition original source markers by destination track identity.

    Args:
        source: Original ordered markers, preserving any repeated observations.
        existing: Original live destination identities.

    Returns:
        Missing and already-present markers in original source order.
    """
    present: list[str] = []
    for uri in source:
        if uri.rsplit(":", maxsplit=1)[-1] in existing:
            present.append(uri)
    missing: list[str] = []
    for uri in source:
        if uri not in present:
            missing.append(uri)
    return tuple(missing), tuple(present)


def completed_slugs(slugs: list[str], maximum_length: int = 256) -> list[str]:
    """Validate completed genre identities and retain their first occurrence order.

    Args:
        slugs: Original validated string entries.
        maximum_length: Original maximum slug length.

    Returns:
        First occurrences of valid original identities.

    Raises:
        ValueError: An entry is empty, too long, padded or contains whitespace.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for slug in slugs:
        if (
            not slug
            or len(slug) > maximum_length
            or slug != slug.strip()
            or any(character.isspace() for character in slug)
        ):
            raise ValueError("completed entries must be valid Every Noise slugs")
        if slug not in seen:
            seen.add(slug)
            cleaned.append(slug)
    return cleaned


def genre_slug(value: str, maximum_length: int = 256) -> str:
    """Apply original run-request rules after completed-slug validation.

    Args:
        value: Original genre identity.
        maximum_length: Original maximum identity length.

    Returns:
        Valid original lowercase alphanumeric identity.

    Raises:
        ValueError: An identity violates original completed/request slug rules.
    """
    validated = completed_slugs([value], maximum_length)[0]
    if re.fullmatch(r"[a-z0-9]+", validated) is None:
        raise ValueError("genre slug must contain only lowercase letters and digits")
    return validated


def genre_name(value: str) -> str:
    """Preserve original display-name whitespace validation.

    Args:
        value: Original already length-validated display name.

    Returns:
        Original unchanged display spelling.

    Raises:
        ValueError: A display name has leading or trailing whitespace.
    """
    if value != value.strip():
        raise ValueError("genre name must not have leading or trailing whitespace")
    return value
