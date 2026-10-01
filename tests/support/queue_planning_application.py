"""Typed in-memory Queue planning ports for frozen original fact scenarios."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace

from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.application.queue_flush_planning import QueuePlanning
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from tests.support.queue_fill import TRACK
from tests.support.queue_flush import SOURCE
from tests.support.queue_planning import RELEASE
from tests.support.queue_planning import PlanningObservations
from tests.support.queue_planning import observations


@dataclass
class MemoryQueuePlanning:
    """Supply original ordered facts without a client, routine or runtime dependency.

    Args:
        observations: Original shared planning facts and read trace.
    """

    observations: PlanningObservations

    def top(self, artist: str) -> tuple[CatalogTrack, ...]:
        """Observe original top-track facts.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ordered top-track facts.
        """
        self.observations.trace.append(["top", artist])
        return self.observations.tracks()

    def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Observe original membership after truncation.

        Args:
            tracks: Original bounded top-track window.

        Returns:
            Original configured liked statuses.
        """
        self.observations.trace.append(
            ["liked", [track.spotify_id for track in tracks]]
        )
        liked: dict[str, bool] = {}
        for index, track in enumerate(tracks):
            liked[track.spotify_id] = index < self.observations.liked_top
        return liked

    def catalog(self, artist: str) -> tuple[RankedRelease, ...]:
        """Observe original ranked catalog facts.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original nonpreferred then preferred facts.
        """
        self.observations.trace.append(["catalog", artist])
        return replace(RELEASE, tier=1), RELEASE

    def assessment(
        self,
        artist: str,
        catalog: tuple[RankedRelease, ...],
        cache: dict[str, tuple[CatalogTrack, ...]],
    ) -> ArtistAssessment:
        """Observe original assessment and its optional shared-cache population.

        Args:
            artist: Original primary artist identity.
            catalog: Original ranked release facts.
            cache: Caller-owned original run-scoped track cache.

        Returns:
            Original configured assessment facts.
        """
        edge = self.observations
        edge.trace.append(["assessment", artist])
        if edge.cached:
            cache[RELEASE.spotify_id] = edge.promotion_tracks()
        return ArtistAssessment(
            edge.liked_total,
            0,
            len(catalog),
            edge.liked_total,
            7,
            False,
            (),
            None,
            TRACK if edge.liked_total else None,
        )

    def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Observe only original uncached preferred-release reads.

        Args:
            release: Original requested preferred release.

        Returns:
            Original ordered marker facts.
        """
        self.observations.trace.append(["release-tracks", release.spotify_id])
        return self.observations.promotion_tracks()


def application_outcome(case: dict[str, object]) -> object:
    """Replay original fact scenarios through independent application ports.

    Args:
        case: Original immutable threshold, cursor and marker facts.

    Returns:
        JSON-compatible original plan and ordered read observations.
    """
    edge = observations(case)
    plan = QueuePlanning(MemoryQueuePlanning(edge)).run(SOURCE, [SOURCE.uri])
    return json.loads(json.dumps({"plan": asdict(plan), "trace": edge.trace}))
