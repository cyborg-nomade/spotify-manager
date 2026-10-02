"""Choose saved/plain canonical editions with original category and chronology rules."""

import re
from collections import defaultdict
from dataclasses import replace

from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.releases import EP_MARKER
from spotify_manager.domain.releases import DateKey
from spotify_manager.domain.releases import EditionKey
from spotify_manager.domain.releases import edition_preference
from spotify_manager.domain.releases import studio_date_key


LIVE_PATTERN = re.compile(
    r"(?:^live(?:!|$|\s)|\blive\b|\bao vivo\b|\ben vivo\b|"
    r"\bin concert\b|\bunplugged\b)",
    re.IGNORECASE,
)
COMPILATION_PATTERN = re.compile(
    r"\b(?:anthology|best of|collection|compilation|greatest hits|rarities)\b",
    re.IGNORECASE,
)


def catalog_type(
    album_type: str,
    album_group: str,
    name: str,
    total: int,
    standard: str | None,
) -> str | None:
    """Retain standard qualification before optional compilation/live/other rules.

    Args:
        album_type: Original casefolded, untrimmed release type.
        album_group: Original casefolded, untrimmed release group.
        name: Original display title.
        total: Original positive-integer track count.
        standard: Original studio/EP qualification, when available.

    Returns:
        Original release classification, excluding true non-EP singles.
    """
    is_ep = album_type == "ep" or (
        album_type == "single" and (total >= 4 or EP_MARKER.search(name))
    )
    if album_type == "single" and not is_ep:
        return None
    if standard is not None:
        return standard
    if (
        album_type == "compilation"
        or album_group == "compilation"
        or COMPILATION_PATTERN.search(name)
    ):
        return "Compilation"
    if LIVE_PATTERN.search(name):
        return "Live"
    return "Other" if album_type == "album" or is_ep else None


def preferred_release(editions: list[CatalogRelease]) -> CatalogRelease:
    """Prefer saved status before plain titles and original stable tie breakers.

    Args:
        editions: Original nonempty edition group.

    Returns:
        Original preferred edition.

    Raises:
        ValueError: The original caller supplies an empty group.
    """
    return min(editions, key=_edition_key)


def _edition_key(release: CatalogRelease) -> EditionKey:
    return edition_preference(
        release.saved,
        release.plain,
        release.edition_rank,
        release.total_tracks,
        release.release_date,
        release.name,
        release.spotify_id,
    )


def canonical_releases(releases: list[CatalogRelease]) -> tuple[CatalogRelease, ...]:
    """Group standard/non-studio identities and retain earliest edition chronology.

    Args:
        releases: Original newest-by-ID catalog facts with saved membership.

    Returns:
        Original canonical chronological catalog.
    """
    grouped: dict[tuple[str, str], list[CatalogRelease]] = defaultdict(list)
    for release in releases:
        category = "standard" if release.default else release.release_type.casefold()
        grouped[(category, release.identity)].append(release)
    selected = []
    for editions in grouped.values():
        preferred = preferred_release(editions)
        chronology = min((item.release_date for item in editions), key=studio_date_key)
        selected.append(
            replace(
                preferred,
                chronology_date=chronology,
                default=any(item.default for item in editions),
            )
        )
    return tuple(sorted(selected, key=_catalog_key))


def _catalog_key(release: CatalogRelease) -> tuple[DateKey, str, str, str]:
    return (
        studio_date_key(release.chronology_date),
        release.release_type,
        release.name.casefold(),
        release.spotify_id,
    )
