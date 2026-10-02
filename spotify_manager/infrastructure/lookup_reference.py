"""Original Spotify reference grammar at the user-input boundary."""

import re
from typing import Literal
from urllib.parse import urlparse


type Resource = Literal["artist", "album", "track"]


def parse(
    reference: str, resource: Resource, pattern: re.Pattern[str]
) -> tuple[str | None, str | None]:
    """Retain original names, bare IDs, URIs and localized share links.

    Args:
        reference: Original user-supplied value.
        resource: Original required resource kind.
        pattern: Original identity grammar.

    Returns:
        Original name/direct-identity lookup arguments.

    Raises:
        ValueError: The original reference is empty or malformed.
    """
    value = reference.strip()
    if not value:
        raise ValueError(f"provide an {resource} name, ID, or Spotify link")
    prefix = f"spotify:{resource}:"
    if value.casefold().startswith(prefix):
        return None, _uri_id(value, prefix, resource, pattern)
    parsed = urlparse(value)
    if parsed.netloc.casefold() in {"open.spotify.com", "www.open.spotify.com"}:
        return None, _share_id(parsed.path, resource, pattern)
    if pattern.fullmatch(value):
        return None, value
    return value, None


def _uri_id(
    value: str, prefix: str, resource: Resource, pattern: re.Pattern[str]
) -> str:
    identifier = value[len(prefix) :].strip()
    if pattern.fullmatch(identifier):
        return identifier
    raise ValueError(f"invalid Spotify {resource} URI")


def _share_id(path: str, resource: Resource, pattern: re.Pattern[str]) -> str:
    parts = []
    for part in path.split("/"):
        if part:
            parts.append(part)
    if parts and parts[0].casefold().startswith("intl-"):
        parts = parts[1:]
    if (
        len(parts) >= 2
        and parts[0].casefold() == resource
        and pattern.fullmatch(parts[1])
    ):
        return parts[1]
    raise ValueError(f"provide a Spotify {resource} share link")
