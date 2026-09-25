"""Edition identity and the intentionally distinct legacy chronology policies."""

import re
from datetime import date

from unidecode import unidecode


EDITION_QUALIFIER = re.compile(
    r"\b(?:anniversary|bonus|collector(?:'s)?|deluxe|edition|expanded|legacy|"
    r"mono|remaster(?:ed)?|reissue|special|stereo|super deluxe)\b",
    re.IGNORECASE,
)
BRACKETED_SUFFIX = re.compile(r"\s*[\[(]([^)\]]+)[)\]]\s*$")
DASHED_SUFFIX = re.compile(r"\s+[-\N{EN DASH}\N{EM DASH}]\s+(.+?)\s*$")
TRAILING_EDITION = re.compile(
    r"\s+(?:(?:\d{2,4}(?:st|nd|rd|th)?\s+)?"
    r"(?:anniversary|deluxe|expanded|legacy|remaster(?:ed)?|reissue|special)"
    r"(?:\s+(?:edition|version))?)\s*$",
    re.IGNORECASE,
)
EP_MARKER = re.compile(r"(?:^|[\s\-[(])e\.?p\.?(?:$|[\s\-)\]])", re.IGNORECASE)
NON_STUDIO_PATTERNS = (
    re.compile(
        r"^live(?:!|$|\s+(?:at|from|in|on)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:[\[(][^)\]]*\blive\b[^)\]]*[)\]]|"
        r"\s[-\N{EN DASH}\N{EM DASH}]\s.*\blive\b.*)$",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:ao vivo|en vivo|in concert|unplugged)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:anthology|best of|collection|compilation|greatest hits|"
        r"rarities)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:cast recording|motion picture|original score|soundtrack)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:bootleg|demos?|karaoke|remix(?:es)?)\b", re.IGNORECASE),
)


type DateKey = tuple[int, int, int, str]
type EditionKey = tuple[bool, bool, int, int, DateKey, str, str]


def _edition_suffix_start(base: str) -> int | None:
    for pattern in (BRACKETED_SUFFIX, DASHED_SUFFIX):
        match = pattern.search(base)
        if match and EDITION_QUALIFIER.search(match.group(1)):
            return match.start()
    match = TRAILING_EDITION.search(base)
    return match.start() if match else None


def edition_details(name: str) -> tuple[str, int]:
    """Remove recognized edition suffixes while counting their penalties.

    Args:
        name: Original release title.

    Returns:
        Edition-neutral title and number of removed decorations. An entirely
        stripped title falls back to the trimmed original title.
    """
    base = name.strip()
    penalty = 0
    start = _edition_suffix_start(base)
    while start is not None:
        base = base[:start].strip()
        penalty += 1
        start = _edition_suffix_start(base)
    return base or name.strip(), penalty


def release_identity(name: str) -> str:
    """Normalize editions, accents, punctuation, and spacing for release identity.

    Args:
        name: Original release title.

    Returns:
        Lowercase ASCII words separated by single spaces.
    """
    base, _penalty = edition_details(name)
    normalized = re.sub(r"[^a-z0-9]+", " ", unidecode(base).casefold())
    return " ".join(normalized.split())


def is_non_studio_title(name: str) -> bool:
    """Recognize the existing conservative live/compilation/soundtrack exclusions.

    Args:
        name: Original release title.

    Returns:
        Whether the title matches a legacy non-studio pattern.
    """
    return any(pattern.search(name) for pattern in NON_STUDIO_PATTERNS)


def studio_date_key(value: str) -> DateKey:
    """Order valid partial dates at the start of their year or month.

    Args:
        value: Spotify date string; invalid dates and Unknown sort last.

    Returns:
        Validity group, ordinal, padding, and original string for stable ties.
    """
    if value == "Unknown":
        return (1, 9999, 12, value)
    try:
        parts = [int(part) for part in value.split("-")]
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        parsed = date(year, month, day)
    except ValueError, IndexError:
        return (1, 9999, 12, value)
    return (0, parsed.toordinal(), 0, value)


def review_date_key(value: str) -> DateKey:
    """Order review-catalog partial dates using year/month-end defaults.

    Args:
        value: Original release date; calendar-invalid numeric parts stay accepted.

    Returns:
        Year, month, day, and original string, preserving tolerant legacy ordering.
    """
    try:
        parts = [int(part) for part in value.split("-")]
    except ValueError:
        return (9999, 12, 31, value)
    return (
        parts[0] if parts else 9999,
        parts[1] if len(parts) > 1 else 12,
        parts[2] if len(parts) > 2 else 31,
        value,
    )


def edition_preference(
    saved: bool,
    plain: bool,
    edition_rank: int,
    total_tracks: int,
    release_date: str,
    name: str,
    spotify_id: str,
) -> EditionKey:
    """Rank editions using saved status, decoration, size, and stable tie breakers.

    Args:
        saved: Whether the edition is saved.
        plain: Whether the title is undecorated.
        edition_rank: Number of recognized decorations.
        total_tracks: Reported track count.
        release_date: Date parsed under the studio chronology policy.
        name: Display title used for case-insensitive ties.
        spotify_id: Final deterministic tie breaker.

    Returns:
        Sort key with the preferred edition first.
    """
    return (
        not saved,
        not plain,
        edition_rank,
        total_tracks,
        studio_date_key(release_date),
        name.casefold(),
        spotify_id,
    )
