"""Resolve and confirm a current edition before saving an existing artist's plan."""

from dataclasses import dataclass
from dataclasses import replace

from spotify_manager.application.discovery_observations import DiscoveryCatalog
from spotify_manager.application.new_kids_plan_selection import ReleasePlanStoppedError
from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.ports.new_kids_plans import ReleasePlanDraft
from spotify_manager.application.ports.new_kids_plans import ReleasePlanReader
from spotify_manager.application.ports.new_kids_plans import ReleasePlanSubmission
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_progression import source_release
from spotify_manager.domain.new_kids_migration import current_track_matches
from spotify_manager.domain.new_kids_migration import migration_position
from spotify_manager.domain.new_kids_plans import ReleasePlan
from spotify_manager.domain.new_kids_plans import select_plan


class MigrationReleaseMissingError(NewKidsError):
    """An exact current edition cannot be read; require explicit resolution."""


def _catalogue(
    releases: tuple[RankedRelease, ...], source: PlaylistTrack, artist_id: str
) -> tuple[RankedRelease, ...]:
    current = source_release(source)
    remaining = []
    for release in releases:
        if release.spotify_id == current.spotify_id:
            current = release
        else:
            remaining.append(release)
    if source.primary_artist_id != artist_id:
        current = replace(
            current,
            primary_artist_id=source.primary_artist_id,
            primary_artist_name=source.primary_artist_name,
        )
    return (current, *remaining)


def _primary(
    release: RankedRelease, tracks: tuple[CatalogTrack, ...]
) -> tuple[CatalogTrack, ...]:
    artist = release.primary_artist_id
    return tuple(track for track in tracks if track.primary_artist_id == artist)


@dataclass(frozen=True)
class NewKidsMigrationSelection:
    """Own exact current-edition resolution and the existing ordered editor.

    Args:
        catalog: Invocation-owned catalogue and track observations.
        reader: Explicit operator plan interaction.
    """

    catalog: DiscoveryCatalog
    reader: ReleasePlanReader

    async def run(
        self, source: PlaylistTrack, artist_id: str, artist_name: str
    ) -> ReleasePlan | None:
        """Pin the selected order at the existing current release.

        Args:
            source: Current live playlist marker, never replaced by migration.
            artist_id: Logical catalogue identity.
            artist_name: Logical display name.

        Returns:
            Accepted plan, or None when this artist is skipped for the invocation.

        Raises:
            ReleasePlanStoppedError: The operator quits before acceptance.
            NewKidsError: Nonrecoverable external observations fail.
        """
        releases = _catalogue(await self.catalog.ranked(artist_id), source, artist_id)
        draft = await self._draft(source, artist_name, releases)
        while True:
            answer = await self.reader.choose_plan(draft)
            if answer.action == "quit":
                raise ReleasePlanStoppedError("New Kids plan migration stopped.")
            if answer.action == "skip":
                return None
            try:
                return await self._selected(source, draft, answer)
            except (ValueError, MigrationReleaseMissingError) as exc:
                available = _ids(releases)
                selected = tuple(key for key in answer.release_ids if key in available)
                draft = replace(draft, notice=str(exc), selected_ids=selected)

    async def _draft(
        self, source: PlaylistTrack, artist: str, releases: tuple[RankedRelease, ...]
    ) -> ReleasePlanDraft:
        current = releases[0]
        known = False
        try:
            tracks = _primary(current, await self.catalog.tracks(current))
            known = current_track_matches(tracks, source.spotify_id, source.name, False)
        except MigrationReleaseMissingError:
            pass
        return ReleasePlanDraft(
            artist,
            releases,
            source.release.name,
            "Choose the current edition and confirm its track mapping."
            if not known
            else "Earlier entries count as completed; retain the current track.",
            migration=True,
            current_release_id=current.spotify_id if known else None,
            current_track=source.name,
            selected_ids=(current.spotify_id,) if known else (),
        )

    async def _selected(
        self,
        source: PlaylistTrack,
        draft: ReleasePlanDraft,
        answer: ReleasePlanSubmission,
    ) -> ReleasePlan:
        if draft.current_release_id and answer.current_release_id not in {
            None,
            draft.current_release_id,
        }:
            raise ValueError("Keep the identified current album in the plan.")
        current_id = draft.current_release_id or answer.current_release_id
        if not current_id:
            raise ValueError("Choose the current album edition before confirming.")
        if draft.current_release_id is None and not answer.confirm_current:
            raise ValueError("Confirm which edition contains the current track.")
        plan = select_plan(draft.releases, answer.release_ids, answer.confirm_short)
        plan = migration_position(plan, current_id)
        current = plan.releases[plan.position]
        tracks = _primary(current, await self.catalog.tracks(current))
        if not current_track_matches(
            tracks, source.spotify_id, source.name, answer.confirm_current
        ):
            raise ValueError(
                "This edition does not identify the current track uniquely. "
                "Choose an edition containing that track."
            )
        return plan


def _ids(releases: tuple[RankedRelease, ...]) -> set[str]:
    return {release.spotify_id for release in releases}
