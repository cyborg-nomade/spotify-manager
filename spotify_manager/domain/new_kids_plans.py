"""Ordered, exact-release listening plans independent of listening history."""

from dataclasses import dataclass

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease


@dataclass(frozen=True)
class ReleasePlan:
    """Pin an artist's chosen releases and the currently active position.

    Args:
        releases: One to four distinct releases in listening order.
        position: Zero-based current release position.
    """

    releases: tuple[RankedRelease, ...]
    position: int = 0


def select_plan(
    catalog: tuple[RankedRelease, ...], identities: tuple[str, ...], short: bool
) -> ReleasePlan:
    """Validate explicit order without automatically including the queue album.

    Args:
        catalog: Offered complete discography, including optional categories.
        identities: Exact release IDs in operator-selected order.
        short: Explicit acknowledgement of fewer than four releases.

    Returns:
        A new plan starting at its first release.

    Raises:
        ValueError: Empty, oversized, duplicate, unknown or unconfirmed short plan.
    """
    available = {release.spotify_id: release for release in catalog}
    validate_plan_ids(identities, tuple(available), short)
    releases = tuple(available[identity] for identity in identities)
    return ReleasePlan(releases)


def validate_plan_ids(
    identities: tuple[str, ...], available: tuple[str, ...], short: bool
) -> None:
    """Check the ordered selection at application and interface boundaries.

    Args:
        identities: Selected IDs in listening order.
        available: IDs offered by this exact draft.
        short: Explicit shorter-plan confirmation.

    Raises:
        ValueError: Selection violates size, uniqueness, availability or confirmation.
    """
    if not 1 <= len(identities) <= 4:
        raise ValueError("Choose between one and four releases.")
    if len(identities) < 4 and not short:
        raise ValueError("Confirm the shorter plan explicitly.")
    if len(set(identities)) != len(identities):
        raise ValueError("Choose each release only once.")
    if not set(identities) <= set(available):
        raise ValueError("A selected release is not in this discography.")


def default_plan_release(release: RankedRelease) -> bool:
    """Identify the studio albums and EPs shown initially.

    Args:
        release: Classified canonical release.

    Returns:
        Whether this release belongs in the default catalogue view.
    """
    return release.release_type in {"Album", "EP"}


def plan_marker(release: RankedRelease, track: CatalogTrack) -> PlaylistTrack:
    """Attach the pinned release to its first playable primary-artist track.

    Args:
        release: Exact chosen release.
        track: Accepted first primary-artist track.

    Returns:
        A normal playlist marker for the existing transfer/execution boundaries.
    """
    candidate = ReleaseCandidate(
        release.spotify_id,
        release.uri,
        release.name,
        release.release_type,
        release.release_date,
        release.total_tracks,
        release.primary_artist_id,
        release.primary_artist_name,
    )
    return PlaylistTrack(
        track.spotify_id,
        track.uri,
        track.name,
        track.primary_artist_id,
        track.primary_artist_name,
        candidate,
    )
