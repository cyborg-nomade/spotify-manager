"""Exact Spotify album identities and chronological explicit release options."""

import re
from dataclasses import dataclass

from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.releases import DateKey
from spotify_manager.domain.releases import studio_date_key


ALBUM_ID = re.compile(r"[A-Za-z0-9]{22}")
ALBUM_URL = re.compile(
    r"https://open\.spotify\.com/(?:intl-[A-Za-z-]+/)?album/"
    r"([A-Za-z0-9]{22})/?(?:[?#][^\s]*)?",
    re.IGNORECASE,
)


def split_album_references(value: str) -> tuple[str, ...]:
    """Split pasted album references at spaces, newlines, commas or semicolons.

    Args:
        value: Operator's pasted reference list.

    Returns:
        Nonempty references in input order.
    """
    references = []
    for part in re.split(r"[\s,;]+", value.strip()):
        if part:
            references.append(part)
    return tuple(references)


@dataclass(frozen=True)
class ReviewRelease:
    """One fetched or explicitly linked edition offered for selection.

    Args:
        release: Exact edition facts retained in the resulting plan.
        artists: Display credits for a linked record, including other artists.
        linked: Whether the operator explicitly supplied this edition.
    """

    release: CatalogRelease
    artists: tuple[str, ...] = ()
    linked: bool = False


def album_reference(value: str) -> str:
    """Parse direct Spotify album links, localized links, URIs or bare IDs.

    Args:
        value: Operator-supplied album reference with optional surrounding space.

    Returns:
        Exact Spotify album identifier, ignoring URL tracking query parameters.

    Raises:
        ValueError: The input is not a supported direct album reference.
    """
    text = value.strip()
    if ALBUM_ID.fullmatch(text):
        return text
    if text.startswith("spotify:album:") and ALBUM_ID.fullmatch(text[14:]):
        return text[14:]
    match = ALBUM_URL.fullmatch(text)
    if match:
        return match.group(1)
    raise ValueError("Use a Spotify album link, spotify:album URI or album ID.")


def merge_review_release(
    entries: tuple[ReviewRelease, ...], addition: ReviewRelease
) -> tuple[ReviewRelease, ...]:
    """Deduplicate exact IDs while preserving explicitly chosen alternate editions.

    Args:
        entries: Current fetched and linked options.
        addition: Newly resolved explicit edition.

    Returns:
        Chronological options retaining distinct edition identities.
    """
    for entry in entries:
        if entry.release.spotify_id == addition.release.spotify_id:
            return entries
    return tuple(sorted((*entries, addition), key=_review_key))


def _review_key(entry: ReviewRelease) -> tuple[DateKey, str, str, str]:
    release = entry.release
    return (
        studio_date_key(release.chronology_date),
        release.release_type,
        release.name.casefold(),
        release.spotify_id,
    )
