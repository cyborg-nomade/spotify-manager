"""Freeze original Queue live planning thresholds, cursor behavior and read caches."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.application.new_kids_values import ArtistAssessment
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.infrastructure.legacy import queue_planning as composition
from spotify_manager.infrastructure.legacy.artist_assessment import (
    LegacyAssessmentCatalog,
)
from spotify_manager.routines import new_kids
from spotify_manager.routines import the_queue as legacy
from tests.support.queue_fill import TRACK
from tests.support.queue_flush import SOURCE


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/queue_planning.json"
RELEASE = RankedRelease(
    "release",
    "spotify:album:release",
    "Release",
    "Album",
    "2020",
    3,
    "artist",
    "Artist",
    50,
    0,
    0,
    "release",
    False,
    True,
)


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


@dataclass
class PlanningObservations:
    """Supply original observed facts and record ordered catalog/cache boundaries.

    Args:
        liked_total: Original liked primary-catalog count.
        liked_top: Original liked top-track count.
        position: Original current marker position or absent.
        promotion: Whether an eligible promotion marker exists.
        cached: Whether assessment already populated its tracks.
        trace: Original ordered observation trace.
    """

    liked_total: int
    liked_top: int
    position: str
    promotion: bool
    cached: bool
    trace: list[list[object]] = field(default_factory=list)

    def tracks(self) -> tuple[CatalogTrack, ...]:
        """Build the original ordered top-track facts.

        Returns:
            Seven original marker facts with configured cursor position.
        """
        tracks: list[CatalogTrack] = []
        for index in range(7):
            identity = f"t{index}"
            if (self.position == "first" and index == 0) or (
                self.position == "last" and index == 6
            ):
                identity = "source"
            tracks.append(
                replace(TRACK, spotify_id=identity, uri=f"spotify:track:{identity}")
            )
        return tuple(tracks)

    def top(
        self,
        spotify: Spotify,
        artist: str,
        retry: legacy.RetryCall,
    ) -> tuple[dict[str, int], tuple[CatalogTrack, ...]]:
        """Observe original top-track reads before membership and catalog.

        Args:
            spotify: Original client boundary.
            artist: Original primary artist identity.
            retry: Original retry boundary.

        Returns:
            Original ranks and ordered top tracks.
        """
        self.trace.append(["top", artist])
        return {}, self.tracks()

    def liked(
        self,
        spotify: Spotify,
        tracks: tuple[CatalogTrack, ...],
        retry: legacy.RetryCall,
    ) -> dict[str, bool]:
        """Observe original membership after top-track truncation.

        Args:
            spotify: Original client boundary.
            tracks: Original top-track window.
            retry: Original retry boundary.

        Returns:
            Original liked membership facts.
        """
        self.trace.append(["liked", [track.spotify_id for track in tracks]])
        return {
            track.spotify_id: index < self.liked_top
            for index, track in enumerate(tracks)
        }

    def catalog(
        self,
        spotify: Spotify,
        artist: str,
        retry: legacy.RetryCall,
    ) -> tuple[RankedRelease, ...]:
        """Observe original ranked catalog after top membership.

        Args:
            spotify: Original client boundary.
            artist: Original primary artist identity.
            retry: Original retry boundary.

        Returns:
            Original nonpreferred then preferred release facts.
        """
        self.trace.append(["catalog", artist])
        return (replace(RELEASE, tier=1), RELEASE)

    def assessment(
        self,
        spotify: Spotify,
        artist: str,
        catalog: tuple[RankedRelease, ...],
        retry: legacy.RetryCall,
        cache: dict[str, tuple[CatalogTrack, ...]],
    ) -> ArtistAssessment:
        """Observe original assessment and optional shared-cache population.

        Args:
            spotify: Original client boundary.
            artist: Original primary artist identity.
            catalog: Original ranked catalog facts.
            retry: Original retry boundary.
            cache: Caller-owned run-scoped track cache.

        Returns:
            Original assessment facts needed by Queue progression.
        """
        self.trace.append(["assessment", artist])
        if self.cached:
            cache[RELEASE.spotify_id] = self.promotion_tracks()
        return ArtistAssessment(
            self.liked_total,
            0,
            len(catalog),
            self.liked_total,
            7,
            False,
            (),
            None,
            TRACK if self.liked_total else None,
        )

    def promotion_tracks(self) -> tuple[CatalogTrack, ...]:
        """Build original promotion marker facts in release order.

        Returns:
            An ineligible first credit followed by the configured eligible marker.
        """
        other = replace(TRACK, primary_artist_id="other")
        return (other, TRACK) if self.promotion else (other,)

    def release_tracks(
        self,
        spotify: Spotify,
        release: RankedRelease,
        retry: legacy.RetryCall,
    ) -> tuple[CatalogTrack, ...]:
        """Observe uncached promotion reads only for preferred releases.

        Args:
            spotify: Original client boundary.
            release: Original requested preferred release.
            retry: Original retry boundary.

        Returns:
            Original ordered promotion marker facts.
        """
        self.trace.append(["release-tracks", release.spotify_id])
        return self.promotion_tracks()


def original_outcome(case: dict[str, object]) -> object:
    """Observe original live decisions with shared assessment and cache seams.

    Args:
        case: Original threshold, cursor and cached marker facts.

    Returns:
        JSON-compatible original plan and read trace.
    """
    edge = observations(case)
    with (
        patch.object(new_kids, "load_top_track_data", edge.top),
        patch.object(legacy, "_liked_statuses", edge.liked),
        patch.object(new_kids, "load_ranked_catalog", edge.catalog),
        patch.object(composition, "assess_artist", partial(_assessment, edge)),
        patch.object(new_kids, "load_release_tracks", edge.release_tracks),
    ):
        plan = legacy._plan_flush_entry(
            cast(Spotify, edge), SOURCE, [SOURCE.uri], _immediate
        )
    return json.loads(json.dumps({"plan": plan, "trace": edge.trace}))


def observations(case: dict[str, object]) -> PlanningObservations:
    """Build original planning facts from a trusted immutable scenario.

    Args:
        case: Original scenario fields.

    Returns:
        Typed in-memory planning observations.
    """
    return PlanningObservations(
        cast(int, case["liked_total"]),
        cast(int, case["liked_top"]),
        cast(str, case["position"]),
        cast(bool, case["promotion"]),
        cast(bool, case["cached"]),
    )


def cases() -> list[tuple[str, dict[str, object]]]:
    """Read immutable original Queue planning observations.

    Returns:
        Named original inputs and plans with ordered read traces.
    """
    raw = cast(dict[str, dict[str, object]], json.loads(FIXTURE.read_text()))
    return list(raw.items())


def _assessment(
    edge: PlanningObservations,
    access: LegacyAssessmentCatalog,
    artist: str,
    catalog: tuple[RankedRelease, ...],
    cache: dict[str, tuple[CatalogTrack, ...]],
) -> ArtistAssessment:
    return edge.assessment(access.client, artist, catalog, access.retry, cache)
