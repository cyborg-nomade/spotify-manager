"""Independent New Wine observations, effects and accepted-failure boundaries."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime

from spotify_manager.application.new_wine import NewWineDependencies
from spotify_manager.application.new_wine import NewWineOptions
from spotify_manager.application.new_wine_observations import WineObservations
from spotify_manager.application.new_wine_values import CellarRefillSummary
from spotify_manager.application.new_wine_values import FlushResult
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.models.lookups import AlbumEvaluation
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
ALBUM = SOURCE.release
TARGET = release_track("target")
FOLLOWUP = playlist_track("followup", studio_release("other", "Other")).release
NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)
OPTIONS = NewWineOptions("new", "sauvignon", None, False, False, False)


def _state() -> dict[str, object]:
    return {"version": 1, "track_progress": {}, "active_run": None}


def _playlists() -> dict[str, list[PlaylistTrack | ReleaseTrack]]:
    return {"new": [SOURCE], "sauvignon": []}


def _tracks() -> dict[str, tuple[ReleaseTrack, ...]]:
    return {ALBUM.spotify_id: (release_track("source"), TARGET)}


@dataclass
class MemoryWine:
    """Keep live effects separate from durable checkpoints for restart assertions.

    Args:
        playlists: Mutable remote marker observations.
        stored: Last accepted namespace checkpoint.
        release_tracks: Scripted release tracks.
        candidates: Current-year releases.
        liked: Live liked membership.
        saved_albums: Live saved-album membership.
        choices: Scripted release choices; default is finish.
        endpoints: Scripted endpoint choices; default is continue.
        events: Ordered boundary observations.
        audits: Accepted flush results.
        failure: One boundary to interrupt.
        accepted: Whether the interruption follows acceptance.
        occurrence: Boundary invocation to interrupt.
        counts: Per-boundary invocation counts.
    """

    playlists: dict[str, list[PlaylistTrack | ReleaseTrack]] = field(
        default_factory=_playlists
    )
    stored: dict[str, object] = field(default_factory=_state)
    release_tracks: dict[str, tuple[ReleaseTrack, ...]] = field(default_factory=_tracks)
    candidates: tuple[ReleaseCandidate, ...] = ()
    liked: set[str] = field(default_factory=set)
    saved_albums: set[str] = field(default_factory=set)
    choices: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    events: list[tuple[str, object]] = field(default_factory=list)
    audits: list[FlushResult] = field(default_factory=list)
    failure: str | None = None
    accepted: bool = False
    occurrence: int = 1
    counts: dict[str, int] = field(default_factory=dict)

    def _before(self, name: str, value: object = None) -> None:
        self.events.append((name, deepcopy(value)))
        self.counts[name] = self.counts.get(name, 0) + 1
        self._fault(name, False)

    def _fault(self, name: str, accepted: bool) -> None:
        if (name, accepted, self.counts.get(name)) != (
            self.failure,
            self.accepted,
            self.occurrence,
        ):
            return
        self.failure = None
        raise RuntimeError(f"{name} interrupted")

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Read live markers, reconstructing appended values for a new invocation.

        Args:
            playlist_id: Requested destination.

        Returns:
            Live markers in accepted order.
        """
        self._before("playlist", playlist_id)
        return tuple(_marker(track) for track in self.playlists[playlist_id])

    def load_state(self, dry_run: bool) -> dict[str, object]:
        """Read detached state or preview defaults.

        Args:
            dry_run: Whether to ignore the durable checkpoint.

        Returns:
            Working namespace detached from the persisted value.
        """
        self._before("load", dry_run)
        return _state() if dry_run else deepcopy(self.stored)

    def save(self, state: dict[str, object]) -> None:
        """Accept a detached checkpoint.

        Args:
            state: Complete mutable namespace.

        Raises:
            RuntimeError: The scripted checkpoint interruption occurs.
        """
        self._before("save", state)
        self.stored = deepcopy(state)
        self._fault("save", True)

    def append(self, playlist_id: str, track: ReleaseTrack) -> None:
        """Accept one remote append.

        Args:
            playlist_id: Target playlist.
            track: Replacement marker.

        Raises:
            RuntimeError: The scripted append interruption occurs.
        """
        self._before("append", (playlist_id, track.spotify_id))
        self.playlists[playlist_id].append(track)
        self._fault("append", True)

    def remove(self, playlist_id: str, source: PlaylistTrack) -> None:
        """Accept remote removal of all matching source IDs.

        Args:
            playlist_id: Source playlist.
            source: Original marker.

        Raises:
            RuntimeError: The scripted removal interruption occurs.
        """
        self._before("remove", source.spotify_id)
        remaining = []
        for track in self.playlists[playlist_id]:
            if track.spotify_id != source.spotify_id:
                remaining.append(track)
        self.playlists[playlist_id] = remaining
        self._fault("remove", True)

    def saved(self, release: ReleaseCandidate, *, removing: bool = False) -> bool:
        """Observe current saved membership.

        Args:
            release: Selected release.
            removing: Whether the request belongs to the drop path.

        Returns:
            Current remote membership.
        """
        self._before("saved", (release.spotify_id, removing))
        return release.spotify_id in self.saved_albums

    def save_album(self, release: ReleaseCandidate) -> None:
        """Accept a remote save.

        Args:
            release: Qualifying release.

        Raises:
            RuntimeError: The scripted save interruption occurs.
        """
        self._before("save_album", release.spotify_id)
        self.saved_albums.add(release.spotify_id)
        self._fault("save_album", True)

    def unsave_album(self, release: ReleaseCandidate) -> None:
        """Accept a remote unsave.

        Args:
            release: Rejected release.

        Raises:
            RuntimeError: The scripted unsave interruption occurs.
        """
        self._before("unsave_album", release.spotify_id)
        self.saved_albums.discard(release.spotify_id)
        self._fault("unsave_album", True)

    def mirror_album(self, release: ReleaseCandidate) -> None:
        """Record mirror publication.

        Args:
            release: Qualifying release.

        Raises:
            RuntimeError: The scripted publication interruption occurs.
        """
        self._before("mirror", release.spotify_id)
        self._fault("mirror", True)

    def remove_mirror_album(self, release: ReleaseCandidate) -> None:
        """Record mirror removal.

        Args:
            release: Rejected release.

        Raises:
            RuntimeError: The scripted publication interruption occurs.
        """
        self._before("remove_mirror", release.spotify_id)
        self._fault("remove_mirror", True)

    def removed_audit(
        self, release: ReleaseCandidate, evaluation: AlbumEvaluation, reason: str
    ) -> None:
        """Record the recovery log boundary.

        Args:
            release: Removed album.
            evaluation: Accepted keep evaluation.
            reason: Original removal reason.

        Raises:
            RuntimeError: The scripted audit interruption occurs.
        """
        self._before("removed_audit", (release.spotify_id, reason))
        self._fault("removed_audit", True)

    def audit(self, run_id: str, result: FlushResult) -> None:
        """Accept a flush result, including preview results.

        Args:
            run_id: Original run identifier.
            result: Completed or skipped outcome.

        Raises:
            RuntimeError: The scripted audit interruption occurs.
        """
        self._before("audit", (run_id, result))
        self.audits.append(result)
        self._fault("audit", True)

    def refill(
        self,
        cellar_id: str,
        no_discovery: bool,
        dry_run: bool,
        state: dict[str, object],
        run: dict[str, object],
        projected: set[str] | None,
    ) -> CellarRefillSummary:
        """Observe the independently tested cellar integration boundary.

        Args:
            cellar_id: Effective source setting.
            no_discovery: Effective eligibility mode.
            dry_run: Invocation mode.
            state: Complete namespace.
            run: Current run.
            projected: Preview membership after transitions.

        Returns:
            Empty refill summary.
        """
        self._before("refill", (cellar_id, no_discovery, dry_run, projected))
        return CellarRefillSummary(10, 0, 0, 0, 0, 0, no_discovery, ())

    def tracks(self, release: ReleaseCandidate) -> tuple[ReleaseTrack, ...]:
        """Observe ordered tracks.

        Args:
            release: Requested release.

        Returns:
            Scripted tracks, including empty responses.
        """
        self._before("tracks", release.spotify_id)
        return self.release_tracks.get(release.spotify_id, ())

    def releases(self, artist_id: str, year: int) -> tuple[ReleaseCandidate, ...]:
        """Observe current-year candidates.

        Args:
            artist_id: Requested artist.
            year: Invocation year.

        Returns:
            Scripted release sequence.
        """
        self._before("releases", (artist_id, year))
        return self.candidates

    def likes(self, ids: list[str], cache: dict[str, bool]) -> None:
        """Observe only previously unseen memberships.

        Args:
            ids: Ordered track observations.
            cache: Run-scoped results updated in place.
        """
        self._before("likes", ids)
        for identifier in ids:
            if identifier not in cache:
                cache[identifier] = identifier in self.liked

    def choose(
        self, source: PlaylistTrack, candidates: tuple[ReleaseCandidate, ...]
    ) -> str:
        """Return the next operator release choice.

        Args:
            source: Original marker.
            candidates: Available selections.

        Returns:
            Scripted choice, defaulting to finish.
        """
        self._before("choose", (source, candidates))
        return self.choices.pop(0) if self.choices else "finish"

    def endpoint(
        self, source: PlaylistTrack, tracks: tuple[ReleaseTrack, ...], index: int
    ) -> str:
        """Return the next endpoint choice.

        Args:
            source: Original marker.
            tracks: Complete observed release.
            index: Source position.

        Returns:
            Scripted choice, defaulting to continue.
        """
        self._before("endpoint", (source, tracks, index))
        return self.endpoints.pop(0) if self.endpoints else "continue"

    def checkpoint(self) -> None:
        """Record an accepted planner choice checkpoint."""
        self._before("checkpoint")

    def clock(self) -> datetime:
        """Observe a clock read.

        Returns:
            Fixed UTC instant.
        """
        self._before("clock")
        return NOW

    def progress(self, completed: int, total: int, label: str) -> None:
        """Record progress and cancellation boundaries.

        Args:
            completed: Existing completed counter.
            total: Number of snapshotted sources.
            label: Original progress text.
        """
        self._before("progress", (completed, total, label))


def _marker(track: PlaylistTrack | ReleaseTrack) -> PlaylistTrack:
    if isinstance(track, PlaylistTrack):
        return track
    return PlaylistTrack(
        track.spotify_id, track.uri, track.name, "artist", "Artist", ALBUM
    )


def dependencies(memory: MemoryWine) -> NewWineDependencies:
    """Create fresh per-invocation caches around retained external state.

    Args:
        memory: Shared simulated boundaries.

    Returns:
        Complete explicit workflow dependencies.
    """
    return NewWineDependencies(
        memory,
        WineObservations(memory, 2026),
        memory.choose,
        memory.endpoint,
        WineMessages(memory.events),
        memory.clock,
        memory.progress,
    )


@dataclass
class WineMessages:
    """Observe presentation timing without importing an interface implementation.

    Args:
        events: Shared ordered boundary observations.
    """

    events: list[tuple[str, object]]

    def canonical(self, source: PlaylistTrack, count: int) -> None:
        """Show an accepted canonical endpoint.

        Args:
            source: Marker chosen as the endpoint.
            count: Canonical track count.
        """
        self.events.append(
            (
                "message:canonical",
                (
                    source,
                    count,
                ),
            )
        )

    def no_releases(self, source: PlaylistTrack, year: int) -> None:
        """Show absence of current-year primary-credit candidates.

        Args:
            source: Original marker.
            year: Existing active year.
        """
        self.events.append(
            (
                "message:no_releases",
                (
                    source,
                    year,
                ),
            )
        )

    def only_single(self, source: PlaylistTrack, year: int) -> None:
        """Show the original automatic single-drop reason.

        Args:
            source: Only current-year single marker.
            year: Existing active year.
        """
        self.events.append(
            (
                "message:only_single",
                (
                    source,
                    year,
                ),
            )
        )

    def empty(self, release: ReleaseCandidate) -> None:
        """Show an empty selected release.

        Args:
            release: Selection with no playable tracks.
        """
        self.events.append(("message:empty", (release,)))

    def empty_continuation(self, release: ReleaseCandidate) -> None:
        """Show why a selected follow-up was omitted.

        Args:
            release: Follow-up with no playable tracks.
        """
        self.events.append(("message:empty_continuation", (release,)))

    def not_kept(self, release: ReleaseCandidate, evaluation: AlbumEvaluation) -> None:
        """Show why a Sauvignon album remains unsaved.

        Args:
            release: Completed release.
            evaluation: Observed live keep decision.
        """
        self.events.append(
            (
                "message:not_kept",
                (
                    release,
                    evaluation,
                ),
            )
        )

    def kept(
        self,
        release: ReleaseCandidate,
        evaluation: AlbumEvaluation,
        saved: bool,
        dry_run: bool,
    ) -> None:
        """Show the original save, preview or already-saved outcome.

        Args:
            release: Completed release.
            evaluation: Live keep decision.
            saved: Saved status observed before this effect.
            dry_run: Whether to use preview wording.
        """
        self.events.append(
            (
                "message:kept",
                (
                    release,
                    evaluation,
                    saved,
                    dry_run,
                ),
            )
        )

    def resumed(self, source: PlaylistTrack) -> None:
        """Show execution of a saved plan whose source is already absent.

        Args:
            source: Original saved marker.
        """
        self.events.append(("message:resumed", (source,)))

    def advanced(self, target: ReleaseTrack, dry_run: bool) -> None:
        """Show an accepted or previewed replacement marker.

        Args:
            target: Selected replacement.
            dry_run: Whether to use preview wording.
        """
        self.events.append(
            (
                "message:advanced",
                (
                    target,
                    dry_run,
                ),
            )
        )

    def sauvignon(self, release: ReleaseCandidate, dry_run: bool) -> None:
        """Show a marker added to Sauvignon.

        Args:
            release: Completed release routed to Sauvignon.
            dry_run: Whether to use preview wording.
        """
        self.events.append(
            (
                "message:sauvignon",
                (
                    release,
                    dry_run,
                ),
            )
        )

    def removed_album(
        self,
        release: ReleaseCandidate,
        evaluation: AlbumEvaluation,
        saved: bool,
        dry_run: bool,
    ) -> None:
        """Show album-removal eligibility and its original membership observation.

        Args:
            release: Rejected album.
            evaluation: Live keep decision.
            saved: Status observed before removal.
            dry_run: Whether to use preview wording.
        """
        self.events.append(
            (
                "message:removed_album",
                (
                    release,
                    evaluation,
                    saved,
                    dry_run,
                ),
            )
        )

    def continuation(
        self, release: ReleaseCandidate, target: ReleaseTrack, dry_run: bool
    ) -> None:
        """Show a newly secured follow-up marker.

        Args:
            release: Accepted follow-up release.
            target: First playable follow-up track.
            dry_run: Whether to use preview wording.
        """
        self.events.append(
            (
                "message:continuation",
                (
                    release,
                    target,
                    dry_run,
                ),
            )
        )

    def removed(self, source: PlaylistTrack, dry_run: bool) -> None:
        """Show completion of source removal, including resumed plans.

        Args:
            source: Original marker.
            dry_run: Whether to use preview wording.
        """
        self.events.append(
            (
                "message:removed",
                (
                    source,
                    dry_run,
                ),
            )
        )
