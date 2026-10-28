"""Gather Queue progression facts and resolve promotion markers with shared caches."""

from dataclasses import asdict
from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.artist_assessment import AssessmentCatalog
from spotify_manager.application.artist_assessment import assess_artist
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.queue_flush_decision import QueuePlan
from spotify_manager.domain.queue_flush_decision import choose_queue_action
from spotify_manager.domain.queue_flush_decision import first_primary_marker
from spotify_manager.domain.queue_flush_decision import resolved_promotion


class QueuePlanningCatalog(Protocol):
    """Original ordered top membership, catalog, assessment and marker reads."""

    async def top(self, artist: str) -> tuple[CatalogTrack, ...]:
        """Read original eligible top tracks before membership.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ordered top tracks before truncation.
        """

    async def liked(self, tracks: tuple[CatalogTrack, ...]) -> dict[str, bool]:
        """Read original top membership after window truncation.

        Args:
            tracks: Original bounded top-track window.

        Returns:
            Original liked statuses.
        """

    async def catalog(self, artist: str) -> tuple[RankedRelease, ...]:
        """Read original ranked catalog after top membership.

        Args:
            artist: Original primary artist identity.

        Returns:
            Original ordered ranked releases.
        """

    async def tracks(self, release: RankedRelease) -> tuple[CatalogTrack, ...]:
        """Read a preferred release only when assessment has not populated it.

        Args:
            release: Original requested preferred release.

        Returns:
            Original ordered release tracks.
        """


async def promotion_marker(
    access: QueuePlanningCatalog,
    artist: str,
    catalog: tuple[RankedRelease, ...],
    cache: dict[str, tuple[CatalogTrack, ...]],
) -> tuple[CatalogTrack | None, str | None]:
    """Find the original first preferred primary marker without re-reading cached facts.

    Args:
        access: Original catalog observation boundary.
        artist: Original primary artist identity.
        catalog: Original ranked releases in source order.
        cache: Caller-owned observed release tracks.

    Returns:
        Original eligible marker and release name, or two absent values.
    """
    for release in catalog:
        if release.tier != 0:
            continue
        tracks = cache.get(release.spotify_id)
        if tracks is None:
            tracks = await access.tracks(release)
            cache[release.spotify_id] = tracks
        target = first_primary_marker(tracks, artist)
        if target is not None:
            return target, release.name
    return None, None


@dataclass(frozen=True)
class QueuePlanning:
    """Gather original live facts before pure decisions and promotion resolution.

    Args:
        access: Original catalog observation boundaries.
        assessment: Named original saved, liked and popularity observations.
        top_limit: Original configured top-track window.
    """

    access: QueuePlanningCatalog
    assessment: AssessmentCatalog
    top_limit: int = 10

    async def record(self, source: PlaylistTrack, uris: list[str]) -> dict[str, object]:
        """Build the original durable plan document from observed business facts.

        Args:
            source: Original authoritative source marker.
            uris: Original live or fallback source URIs.

        Returns:
            Original serialized plan before its accepted checkpoint.
        """
        return asdict(await self.run(source, uris))

    async def run(self, source: PlaylistTrack, uris: list[str]) -> QueuePlan:
        """Preserve top, membership, catalog, assessment and marker read order.

        Args:
            source: Original authoritative source marker.
            uris: Original live or fallback source URIs.

        Returns:
            Original complete plan facts before durable acceptance.
        """
        artist = source.primary_artist_id
        tracks = (await self.access.top(artist))[: self.top_limit]
        liked = await self.access.liked(tracks)
        catalog = await self.access.catalog(artist)
        cache: dict[str, tuple[CatalogTrack, ...]] = {}
        assessment = await assess_artist(self.assessment, artist, catalog, cache)
        decision = choose_queue_action(
            source.spotify_id,
            tracks,
            liked,
            assessment.liked_tracks,
            assessment.top_liked_track,
        )
        release = None
        if decision.action == "promote":
            target, release = await promotion_marker(
                self.access, artist, catalog, cache
            )
            decision = resolved_promotion(decision.reason, target)
        return QueuePlan(
            decision.action,
            uris,
            decision.target,
            release,
            len(tracks),
            sum(liked.values()),
            assessment.liked_tracks,
            decision.reason,
        )
