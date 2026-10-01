"""Load destination membership and apply ordered Wine Cellar cleanup effects."""

from dataclasses import dataclass

from spotify_manager.application.release_progress import ReleaseProgress
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.release_check_values import PlaylistMembership
from spotify_manager.domain.release_check_values import PlaylistSnapshot


@dataclass(frozen=True)
class ReleaseDestinations:
    """Original destination observations retained throughout the release run.

    Args:
        wine_id: Wine Cellar destination identity.
        vintage_id: New Vintage destination identity.
        wine: Mutable Wine Cellar membership after cleanup.
        vintage: Mutable New Vintage membership.
        duplicates: Original planned or accepted Wine Cellar cleanup count.
        composers: Observed owned composer playlists.
    """

    wine_id: str
    vintage_id: str
    wine: PlaylistMembership
    vintage: PlaylistMembership
    duplicates: int
    composers: tuple[OwnedPlaylist, ...]


def _report_cleanup(
    progress: ReleaseProgress, snapshot: PlaylistSnapshot, count: int
) -> None:
    if not count:
        return
    action = "Would remove" if progress.preview else "Removed"
    progress.notify(f"{action} {count} duplicate Wine Cellar track(s)")
    if not progress.preview:
        progress.effects.audit(
            progress.opening.run_id,
            "wine_cellar_deduplicated",
            removed=count,
            retained=len(snapshot.entries) - count,
        )


def load_destinations(
    progress: ReleaseProgress, wine_id: str, vintage_id: str
) -> ReleaseDestinations:
    """Observe destinations and composers in their original accepted-effect order.

    Args:
        progress: Current progress and original external effects.
        wine_id: Wine Cellar identity.
        vintage_id: New Vintage identity.

    Returns:
        Original cleaned destination memberships and composer observations.
    """
    progress.notify("Loading destination playlists")
    snapshot = progress.effects.wine()
    duplicates, wine = progress.effects.cleanup(snapshot, progress.preview)
    _report_cleanup(progress, snapshot, duplicates)
    vintage = progress.effects.vintage()
    progress.notify("Loading classical composer playlists")
    composers = progress.effects.composers()
    return ReleaseDestinations(
        wine_id, vintage_id, wine, vintage, duplicates, composers
    )
