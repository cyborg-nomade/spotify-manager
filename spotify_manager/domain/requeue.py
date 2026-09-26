"""Pure plans for advancing one Requeue for a Dream playlist marker."""

from dataclasses import dataclass
from typing import Literal

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack


type RequeueAction = Literal["advance", "drop", "empty", "skip"]


@dataclass(frozen=True)
class RequeuePlan:
    """One decision over observed playlist and catalog facts.

    Args:
        action: Existing transition kind.
        before: Observed playlist length.
        after: Predicted length under the existing duplicate rules.
        source: Original playlist head, when present.
        target: First playable successor track, when present.
        target_release: Successor release, even when it has no playable tracks.
        already_present: Whether the replacement ID appeared in the original list.
        reason: Existing explanation for a skip, drop, or empty playlist.
    """

    action: RequeueAction
    before: int
    after: int
    source: PlaylistTrack | None = None
    target: ReleaseTrack | None = None
    target_release: DiscographyRelease | None = None
    already_present: bool = False
    reason: str | None = None


def plan_transition(
    playlist: tuple[PlaylistTrack, ...],
    current: DiscographyRelease | None,
    following: DiscographyRelease | None,
    tracks: tuple[ReleaseTrack, ...],
) -> RequeuePlan:
    """Plan a transition without reading state or changing the playlist.

    Args:
        playlist: Original ordered playlist observations.
        current: Canonical release matching the source marker.
        following: Its successor, if any.
        tracks: Ordered playable tracks for that successor.

    Returns:
        The exact legacy action, counts, duplicate observation, and reason.
    """
    before = len(playlist)
    if not playlist:
        return RequeuePlan("empty", 0, 0, reason="playlist is empty")
    source = playlist[0]
    if current is None:
        reason = "current release is not an eligible studio album or EP"
        return RequeuePlan("skip", before, before, source, reason=reason)
    if following is None:
        return RequeuePlan(
            "drop", before, before - 1, source, reason="last eligible release"
        )
    if not tracks:
        return RequeuePlan(
            "skip",
            before,
            before,
            source,
            target_release=following,
            reason="next release has no playable tracks",
        )
    return _advance_plan(playlist, following, tracks[0])


def _advance_plan(
    playlist: tuple[PlaylistTrack, ...],
    release: DiscographyRelease,
    target: ReleaseTrack,
) -> RequeuePlan:
    present = any(track.spotify_id == target.spotify_id for track in playlist)
    return RequeuePlan(
        "advance",
        len(playlist),
        len(playlist) - int(present),
        playlist[0],
        target,
        release,
        present,
    )
