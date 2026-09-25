"""Edition selection and sequential release progression over parsed facts."""

from dataclasses import replace

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.releases import EditionKey
from spotify_manager.domain.releases import edition_preference
from spotify_manager.domain.releases import release_identity
from spotify_manager.domain.releases import studio_date_key


def _edition_key(release: DiscographyRelease) -> EditionKey:
    return edition_preference(
        release.saved,
        release.plain,
        release.edition_rank,
        release.total_tracks,
        release.release_date,
        release.name,
        release.spotify_id,
    )


def _chronology_key(
    release: DiscographyRelease,
) -> tuple[tuple[int, int, int, str], str, str, str]:
    return (
        studio_date_key(release.chronology_date),
        release.release_type,
        release.name.casefold(),
        release.spotify_id,
    )


def select_editions(
    releases: list[DiscographyRelease],
) -> tuple[DiscographyRelease, ...]:
    """Collapse editions and retain the original chronology and tie breakers.

    Args:
        releases: Parsed, eligible candidates with observed saved statuses.

    Returns:
        Preferred editions ordered by their earliest edition date and legacy ties.
    """
    groups: dict[str, list[DiscographyRelease]] = {}
    for release in releases:
        groups.setdefault(release.identity, []).append(release)
    selected = []
    for editions in groups.values():
        preferred = min(editions, key=_edition_key)
        dates = [edition.release_date for edition in editions]
        chronology = min(dates, key=studio_date_key)
        selected.append(replace(preferred, chronology_date=chronology))
    return tuple(sorted(selected, key=_chronology_key))


def release_transition(
    source_name: str, discography: tuple[DiscographyRelease, ...]
) -> tuple[DiscographyRelease | None, DiscographyRelease | None]:
    """Find the first matching canonical release and its immediate successor.

    Args:
        source_name: Playlist marker's release title, including any edition suffix.
        discography: Already-selected and ordered studio albums and EPs.

    Returns:
        Current and next release; an absent current release yields two None values.
    """
    identity = release_identity(source_name)
    for index, release in enumerate(discography):
        if release.identity != identity:
            continue
        following = discography[index + 1 : index + 2]
        return release, following[0] if following else None
    return None, None
