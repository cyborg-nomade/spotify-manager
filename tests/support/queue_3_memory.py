"""In-memory Queue 3 effects for independent execution and coordination contracts."""

from copy import deepcopy
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.models.lookups import AlbumEvaluation
from tests.support.listening_values import playlist_track


@dataclass
class ExecutionMemory:
    """Observe effects and fail before accepting a selected boundary.

    Args:
        failure: Optional failing boundary.
        events: Ordered effect observations.
        remote: Accepted remote marker IDs.
    """

    failure: str | None = None
    events: list[tuple[str, object]] = field(default_factory=list)
    remote: set[str] = field(default_factory=set)

    def _record(self, name: str, value: object) -> None:
        self.events.append((name, value))
        if name == self.failure:
            raise OSError(name)

    def append(
        self, playlist: str, tracks: list[PlaylistTrack], description: str
    ) -> None:
        """Accept marker additions after their failure boundary.

        Args:
            playlist: Queue destination.
            tracks: Replacement markers.
            description: Original retry label.
        """
        self._record("append", (playlist, tracks, description))
        self.remote.update(track.spotify_id for track in tracks)

    def remove(self, playlist: str, uris: list[str], description: str) -> None:
        """Accept marker removals after their failure boundary.

        Args:
            playlist: Queue destination.
            uris: Original removal selection.
            description: Original retry label.
        """
        self._record("remove", (playlist, uris, description))
        self.remote.difference_update(uri.rsplit(":", 1)[-1] for uri in uris)

    def reconcile(self, release: RankedRelease, evaluation: AlbumEvaluation) -> str:
        """Observe library reconciliation before playlist presence checks.

        Args:
            release: Original selected edition adapted for the library workflow.
            evaluation: Accepted saved evaluation.

        Returns:
            Original library action, unused by the Queue 3 executor.
        """
        self._record("library", (release, evaluation))
        return "kept"

    def added(self, name: str, dry_run: bool) -> None:
        """Observe the addition message.

        Args:
            name: Target title.
            dry_run: Preview flag.
        """
        self._record("added", (name, dry_run))

    def removed(self, name: str, dry_run: bool) -> None:
        """Observe the previous-marker removal message.

        Args:
            name: Source title.
            dry_run: Preview flag.
        """
        self._record("removed", (name, dry_run))

    def completed(self, artist: str, dry_run: bool) -> None:
        """Observe final catalog completion.

        Args:
            artist: Logical artist name.
            dry_run: Preview flag.
        """
        self._record("completed", (artist, dry_run))

    def skipped(self, artist: str, reason: object) -> None:
        """Observe a skipped marker.

        Args:
            artist: Logical artist name.
            reason: Original tolerant reason value.
        """
        self._record("skipped", (artist, reason))


@dataclass
class CoordinationMemory(ExecutionMemory):
    """Observe Queue 3 catalogs, choices, clocks, checkpoints and progress.

    Args:
        catalogs: Eligible studio catalogs keyed by logical artist.
        works: Parsed works playlists keyed by playlist ID.
        tracks: Ordered tracks keyed by selected release ID.
        response: Original release transition response.
        composer_response: Original owned-playlist selection response.
        clock_reads: Accepted timestamp reads.
        checkpoints: Accepted detached namespace checkpoints.
    """

    catalogs: dict[str, tuple[DiscographyRelease, ...]] = field(default_factory=dict)
    works: dict[str, tuple[PlaylistTrack, ...]] = field(default_factory=dict)
    tracks: dict[str, tuple[ReleaseTrack, ...]] = field(default_factory=dict)
    response: str = "advance"
    composer_response: str = "works"
    clock_reads: int = 0
    checkpoints: list[dict[str, object]] = field(default_factory=list)

    def load(self) -> dict[str, object]:
        """Reject loading state that bootstrap already prepared.

        Raises:
            AssertionError: A redundant namespace load is attempted.
        """
        raise AssertionError("State is already prepared")

    def save(self, value: dict[str, object], *, message: str | None = None) -> None:
        """Accept a checkpoint after its failure boundary.

        Args:
            value: Complete mutable working namespace.
            message: Optional original store message.
        """
        self._record("checkpoint", deepcopy(value))
        self.checkpoints.append(deepcopy(value))

    def now(self) -> datetime:
        """Read and advance the original UTC clock.

        Returns:
            A timestamp distinct from previous reads.
        """
        self._record("clock", None)
        value = datetime(2026, 9, 28, tzinfo=UTC) + timedelta(seconds=self.clock_reads)
        self.clock_reads += 1
        return value

    def catalog(self, artist_id: str) -> tuple[DiscographyRelease, ...]:
        """Observe the original logical-artist catalog request.

        Args:
            artist_id: Logical artist identifier.

        Returns:
            Configured selected editions or an empty catalog.
        """
        self._record("catalog", artist_id)
        return self.catalogs.get(artist_id, ())

    def playlist(self, playlist_id: str) -> tuple[PlaylistTrack, ...]:
        """Observe a works-playlist request.

        Args:
            playlist_id: Accepted owned playlist identifier.

        Returns:
            Configured ordered markers or an empty playlist.
        """
        self._record("works", playlist_id)
        return self.works.get(playlist_id, ())

    def release_tracks(self, release: DiscographyRelease) -> tuple[ReleaseTrack, ...]:
        """Observe the selected edition's track request.

        Args:
            release: Selected studio edition.

        Returns:
            Configured ordered tracks or an empty release.
        """
        self._record("tracks", release.spotify_id)
        return self.tracks.get(release.spotify_id, ())

    def evaluate(
        self, release: DiscographyRelease, tracks: tuple[ReleaseTrack, ...]
    ) -> AlbumEvaluation:
        """Observe the original live evaluation boundary.

        Args:
            release: Completed selected edition.
            tracks: Complete observed tracks.

        Returns:
            An original-format all-unliked album evaluation.
        """
        self._record("evaluate", release.spotify_id)
        return evaluate_release(playlist_track("unused", release).release, tracks, {})

    def choose(
        self,
        source: PlaylistTrack,
        current: DiscographyRelease,
        following: DiscographyRelease,
    ) -> str:
        """Observe a release-boundary choice.

        Args:
            source: Original marker.
            current: Completed or ineligible source release.
            following: Proposed successor.

        Returns:
            Scripted transition response.
        """
        self._record("choice", (source, current, following))
        return self.response

    def choose_composer(
        self, artist: str, candidates: tuple[OwnedPlaylist, ...]
    ) -> str:
        """Observe ambiguous works-playlist selection.

        Args:
            artist: Logical artist name.
            candidates: Original owned matching playlists.

        Returns:
            Scripted playlist selection or quit response.
        """
        self._record("composer_choice", (artist, candidates))
        return self.composer_response

    def audit(self, event: str, details: dict[str, object]) -> None:
        """Observe the original structured transition audit.

        Args:
            event: Original event identifier.
            details: Original run ID and public result fields.
        """
        self._record("audit", (event, details))

    def started(self, index: int, total: int, artist: str, track: str) -> None:
        """Observe progress before entry planning.

        Args:
            index: One-based original snapshot position.
            total: Complete snapshot size.
            artist: Logical artist name.
            track: Original marker title.
        """
        self._record("started", (index, total, artist, track))

    def finished(self, index: int, total: int, artist: str) -> None:
        """Observe progress after audit and acknowledgment.

        Args:
            index: One-based original snapshot position.
            total: Complete snapshot size.
            artist: Logical artist name.
        """
        self._record("finished", (index, total, artist))

    def stale(self, artist: str) -> None:
        """Observe stale-plan removal before its checkpoint.

        Args:
            artist: Logical artist name.
        """
        self._record("stale", artist)
