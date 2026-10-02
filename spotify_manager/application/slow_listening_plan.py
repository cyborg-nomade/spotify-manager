"""Interactive studio progression, with run-scoped observations and saved choices."""

from collections.abc import Callable
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from spotify_manager.application.slow_listening_values import ReleaseOrderReader
from spotify_manager.application.slow_listening_values import SlowListeningError
from spotify_manager.application.slow_listening_values import TrackActionReader
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.discography import release_transition
from spotify_manager.domain.releases import studio_date_key
from spotify_manager.domain.slow_listening import date_groups
from spotify_manager.domain.slow_listening import track_index


class StudioCatalog(Protocol):
    """Observe studio releases and ordered playable tracks for one run."""

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Read selected editions.

        Args:
            artist_id: Primary artist being advanced.

        Returns:
            Eligible selected editions in chronological order.
        """

    def tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read ordered tracks from one selected edition.

        Args:
            release: Selected studio edition.

        Returns:
            Playable tracks in release order.
        """


@dataclass
class StudioObservations:
    """Cache facts only within a single synchronous routine invocation.

    Args:
        catalog: Existing catalog boundary.
        releases: Previously observed artist catalogs.
        tracks: Previously observed release tracks.
    """

    catalog: StudioCatalog
    releases: dict[str, tuple[DiscographyRelease, ...]] = field(default_factory=dict)
    tracks: dict[str, tuple[ReleaseTrack, ...]] = field(default_factory=dict)

    def discography(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Read an artist once in this invocation.

        Args:
            artist_id: Primary artist to observe.

        Returns:
            Cached or newly observed catalog, including an empty catalog.
        """
        if artist_id not in self.releases:
            self.releases[artist_id] = self.catalog.discography(artist_id)
        return self.releases[artist_id]

    def release_tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Read a release once in this invocation.

        Args:
            release: Selected edition to observe.

        Returns:
            Cached or newly observed playable tracks, including an empty release.
        """
        if release.spotify_id not in self.tracks:
            self.tracks[release.spotify_id] = self.catalog.tracks(release)
        return self.tracks[release.spotify_id]


@dataclass
class ReleaseOrdering:
    """Ask for tie order only when progression reaches a shared release date.

    Args:
        choose: Existing operator ordering callback.
        saved: Mutable persisted preferences, including unrecognized legacy fields.
        persist: Checkpoint callback invoked after each new accepted preference.
    """

    choose: ReleaseOrderReader
    saved: dict[str, object]
    persist: Callable[[], None]

    def ordered(
        self, artist_id: str, releases: tuple[DiscographyRelease, ...]
    ) -> tuple[DiscographyRelease, ...]:
        """Apply a valid saved order or request and save a replacement.

        Args:
            artist_id: Primary artist for the preference key.
            releases: One date group in catalog order.

        Returns:
            The same releases in the accepted order.

        Raises:
            SlowListeningError: The operator omits or duplicates an option.
        """
        if len(releases) < 2:
            return releases
        date = releases[0].chronology_date
        key = f"{artist_id}:{date}"
        stored = self.saved.get(key)
        ids = tuple(str(value) for value in stored) if isinstance(stored, list) else ()
        expected = {release.spotify_id for release in releases}
        if len(ids) != len(releases) or set(ids) != expected:
            ids = self._choose_order(date, releases, expected)
            self.saved[key] = list(ids)
            self.persist()
        by_id = {release.spotify_id: release for release in releases}
        return tuple(by_id[spotify_id] for spotify_id in ids)

    def _choose_order(
        self, date: str, releases: tuple[DiscographyRelease, ...], expected: set[str]
    ) -> tuple[str, ...]:
        ids = self.choose(date, releases)
        if len(ids) != len(releases) or set(ids) != expected:
            raise SlowListeningError("Release ordering must include every option.")
        return ids

    def following(
        self, current: DiscographyRelease, discography: tuple[DiscographyRelease, ...]
    ) -> DiscographyRelease | None:
        """Choose a successor, requesting only tie groups reached at this boundary.

        Args:
            current: Selected edition whose last track has been reached.
            discography: Observed selected studio catalog.

        Returns:
            Next edition or no successor if the current edition is absent or last.
        """
        groups = date_groups(discography)
        date = studio_date_key(current.chronology_date)
        for index, group in enumerate(groups):
            if studio_date_key(group[0].chronology_date) == date:
                return self._successor(current, groups, index)
        return None

    def _successor(
        self,
        current: DiscographyRelease,
        groups: tuple[tuple[DiscographyRelease, ...], ...],
        index: int,
    ) -> DiscographyRelease | None:
        ordered = self.ordered(current.primary_artist_id, groups[index])
        ids = [release.spotify_id for release in ordered]
        if current.spotify_id not in ids:
            return None
        position = ids.index(current.spotify_id)
        if position + 1 < len(ordered):
            return ordered[position + 1]
        if index + 1 == len(groups):
            return None
        return self.ordered(current.primary_artist_id, groups[index + 1])[0]


@dataclass
class TrackSelection:
    """Scan successive studio tracks while preserving skip and choice boundaries.

    Args:
        source: Original playlist marker.
        discography: Selected studio editions.
        observations: Run-scoped track cache and catalog port.
        ordering: Tie choices and checkpoint ownership.
        choose: Operator's advance, skip or quit callback.
        skipped_ids: Previously declined track IDs, updated on new declines.
        persist_skip: Append and checkpoint one newly declined ID.
        skipped_labels: Visible labels accumulated during this scan.
    """

    source: PlaylistTrack
    discography: tuple[DiscographyRelease, ...]
    observations: StudioObservations
    ordering: ReleaseOrdering
    choose: TrackActionReader
    skipped_ids: set[str]
    persist_skip: Callable[[str], None]
    skipped_labels: list[str] = field(default_factory=list)

    def plan(self) -> dict[str, object] | None:
        """Find the next accepted track or retain an explicit skip/completion plan.

        Returns:
            Legacy durable plan, or None when the operator pauses.

        Raises:
            SlowListeningError: A callback returns an invalid choice.
        """
        release, _following = release_transition(
            self.source.release.name, self.discography
        )
        if release is None:
            return _skip(None, "current release is not an eligible studio album or EP")
        tracks = self.observations.release_tracks(release)
        index = track_index(tracks, self.source)
        if index is None:
            return _skip(
                release, "current track could not be mapped to the preferred edition"
            )
        return self._scan(release, tracks, index + 1)

    def _scan(
        self, release: DiscographyRelease, tracks: tuple[ReleaseTrack, ...], index: int
    ) -> dict[str, object] | None:
        while True:
            release, tracks, index, terminal = self._boundary(release, tracks, index)
            if terminal is not None:
                return terminal
            target = tracks[index]
            choice = self._choice(target, release)
            if choice == "quit":
                return None
            if choice == "advance":
                return self._advance(target, release)
            index += 1

    def _boundary(
        self, release: DiscographyRelease, tracks: tuple[ReleaseTrack, ...], index: int
    ) -> tuple[
        DiscographyRelease, tuple[ReleaseTrack, ...], int, dict[str, object] | None
    ]:
        if index < len(tracks):
            return release, tracks, index, None
        following = self.ordering.following(release, self.discography)
        if following is None:
            return release, tracks, index, self._complete(release)
        tracks = self.observations.release_tracks(following)
        if not tracks:
            return following, tracks, 0, self._empty_release(following)
        return following, tracks, 0, None

    def _choice(self, target: ReleaseTrack, release: DiscographyRelease) -> str:
        label = f"{target.name} ({release.name})"
        if target.spotify_id in self.skipped_ids:
            self.skipped_labels.append(label)
            return "skip"
        choice = self.choose(self.source, target, release)
        if choice == "quit" or choice == "advance":
            return choice
        if choice != "skip":
            raise SlowListeningError(
                "Track action must be add, skip candidate, or quit."
            )
        self.skipped_ids.add(target.spotify_id)
        self.persist_skip(target.spotify_id)
        self.skipped_labels.append(label)
        return choice

    def _advance(
        self, target: ReleaseTrack, release: DiscographyRelease
    ) -> dict[str, object]:
        return {
            "action": "advance",
            "target": asdict(target),
            "target_release": asdict(release),
            "skipped_candidates": self.skipped_labels,
            "reason": None,
        }

    def _complete(self, release: DiscographyRelease) -> dict[str, object]:
        reason = (
            "all remaining studio tracks were skipped"
            if self.skipped_labels
            else "last track of the last studio release"
        )
        return {
            "action": "complete",
            "target": None,
            "target_release": asdict(release),
            "skipped_candidates": self.skipped_labels,
            "reason": reason,
            "completion_acknowledged": False,
        }

    def _empty_release(self, release: DiscographyRelease) -> dict[str, object]:
        return {
            "action": "skip",
            "target": None,
            "target_release": asdict(release),
            "skipped_candidates": self.skipped_labels,
            "reason": "next release has no playable tracks",
        }


def _skip(release: DiscographyRelease | None, reason: str) -> dict[str, object]:
    return {
        "action": "skip",
        "target": None,
        "target_release": asdict(release) if release is not None else None,
        "reason": reason,
    }
