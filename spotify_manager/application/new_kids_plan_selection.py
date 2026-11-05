"""Choose exact listening plans before any Queue 2 transfer effects."""

from dataclasses import dataclass
from dataclasses import replace

from spotify_manager.application.discovery_observations import DiscoveryCatalog
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.ports.new_kids_plans import ReleasePlanDraft
from spotify_manager.application.ports.new_kids_plans import ReleasePlanReader
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.new_kids_plans import ReleasePlan
from spotify_manager.domain.new_kids_plans import plan_marker
from spotify_manager.domain.new_kids_plans import select_plan


class ReleasePlanStoppedError(NewKidsError):
    """The operator stopped planning before an unaccepted transfer occurred."""


@dataclass(frozen=True)
class AcceptedReleasePlan:
    """An explicit plan and its validated initial playlist marker.

    Args:
        plan: Accepted release order.
        marker: First playable primary-artist track of its first release.
    """

    plan: ReleasePlan
    marker: PlaylistTrack


@dataclass(frozen=True)
class NewKidsPlanSelection:
    """Resolve the catalogue, read an ordered plan and validate its first track.

    Args:
        catalog: Invocation-owned Spotify reads.
        reader: Named operator interaction boundary.
    """

    catalog: DiscoveryCatalog
    reader: ReleasePlanReader

    async def run(
        self, source: PlaylistTrack, artist_id: str, artist_name: str
    ) -> AcceptedReleasePlan | None:
        """Keep editing invalid choices; skip or stop without transferring a marker.

        Args:
            source: Existing Queue 2 marker, not automatically part of the plan.
            artist_id: Logical artist catalogue identifier.
            artist_name: Logical artist display name.

        Returns:
            Accepted plan and first track, or None for an explicit skip.

        Raises:
            ReleasePlanStoppedError: The operator quits.
            NewKidsError: Spotify cannot supply the chosen release's tracks.
        """
        releases = await self.catalog.ranked(artist_id)
        draft = ReleasePlanDraft(artist_name, releases, source.release.name)
        while True:
            answer = await self.reader.choose_plan(draft)
            if answer.action == "quit":
                raise ReleasePlanStoppedError("New Kids plan selection stopped.")
            if answer.action == "skip":
                return None
            try:
                plan = select_plan(releases, answer.release_ids, answer.confirm_short)
                return await self._accepted(plan, artist_id)
            except ValueError as exc:
                draft = replace(draft, notice=str(exc))

    async def _accepted(self, plan: ReleasePlan, artist_id: str) -> AcceptedReleasePlan:
        release = plan.releases[0]
        tracks = await self.catalog.tracks(release)
        for track in tracks:
            if track.primary_artist_id == artist_id:
                return AcceptedReleasePlan(plan, plan_marker(release, track))
        raise ValueError(f"{release.name} has no playable primary-artist tracks.")
