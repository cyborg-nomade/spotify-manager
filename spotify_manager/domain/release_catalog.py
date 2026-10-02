"""Choose market editions and order current or retained pending releases."""

from datetime import date

from spotify_manager.domain.release_check import release_date_interval
from spotify_manager.domain.release_check import release_identity
from spotify_manager.domain.release_check import release_scope_reason
from spotify_manager.domain.release_check import released_during
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import ReleaseCandidate


def _edition_order(release: ReleaseCandidate) -> tuple[int, str]:
    return -release.total_tracks, release.spotify_id


def _retain_edition(
    current: dict[tuple[str, str, str], ReleaseCandidate],
    duplicates: list[ReleaseCandidate],
    release: ReleaseCandidate,
) -> None:
    identity = release_identity(release)
    existing = current.get(identity)
    if existing is None:
        current[identity] = release
        return
    preferred = min((existing, release), key=_edition_order)
    duplicates.append(release if preferred is existing else existing)
    current[identity] = preferred


def current_editions(
    catalog: tuple[ReleaseCandidate, ...], start: date, end: date
) -> tuple[tuple[ReleaseCandidate, ...], tuple[ReleaseCandidate, ...]]:
    """Retain the largest market edition, breaking track-count ties by identity.

    Args:
        catalog: Catalog observations in their original order.
        start: Inclusive run-window start.
        end: Inclusive run-window end.

    Returns:
        Retained editions in first-identity order and discarded observations in order.
    """
    current: dict[tuple[str, str, str], ReleaseCandidate] = {}
    duplicates: list[ReleaseCandidate] = []
    for release in catalog:
        if released_during(release, start, end):
            _retain_edition(current, duplicates, release)
    return tuple(current.values()), tuple(duplicates)


def eligible_records(
    current: tuple[ReleaseCandidate, ...], rank: int
) -> tuple[ReleaseCandidate, ...]:
    """Select current albums and EPs eligible to contain a reviewed single.

    Args:
        current: Retained current releases in observation order.
        rank: Global listening rank.

    Returns:
        Eligible records in their original order.
    """
    records: list[ReleaseCandidate] = []
    for release in current:
        if (
            release.release_type in {"Album", "EP"}
            and release_scope_reason(release, rank) is None
        ):
            records.append(release)
    return tuple(records)


def _review_order(release: ReleaseCandidate) -> tuple[tuple[date, date], str, str, str]:
    return (
        release_date_interval(release) or (date.max, date.max),
        release.release_type,
        release.name.casefold(),
        release.spotify_id,
    )


def ordered_releases(
    current: tuple[ReleaseCandidate, ...], pending: dict[str, PendingSingle]
) -> tuple[ReleaseCandidate, ...]:
    """Reconsider retained singles absent from the current catalog, in calendar order.

    Args:
        current: Retained current releases.
        pending: Decoded pending singles belonging to this artist.

    Returns:
        Current and otherwise absent pending releases in stable review order.
    """
    releases = list(current)
    current_ids = {release.spotify_id for release in current}
    for release_id, single in pending.items():
        if release_id not in current_ids:
            releases.append(single.release)
    releases.sort(key=_review_order)
    return tuple(releases)
