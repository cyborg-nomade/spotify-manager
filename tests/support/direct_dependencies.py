"""Preserve observed callback arguments when fixtures inject explicit ports."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

from spotify_manager.application.discography_catalog import DiscographyCatalog
from spotify_manager.application.discography_history import DiscographyArtistMapping
from spotify_manager.application.discography_history import DiscographyHistory
from spotify_manager.application.dormant_tracks import DormantLikedTrack
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.infrastructure.discography_observations import (
    DiscographyArtistCatalog,
)
from spotify_manager.infrastructure.discography_observations import DiscographySpotify
from spotify_manager.infrastructure.legacy.dated_history import LegacyDatedHistory
from spotify_manager.infrastructure.legacy.dormant_tracks import LegacyDormantCatalog
from spotify_manager.infrastructure.legacy.recommendations import (
    LegacyRecommendationRun,
)
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio
from spotify_manager.routines import found_art


@dataclass(frozen=True)
class ObservedBlastSelection:
    """Bind an existing batch oracle to the concrete selection boundary.

    Args:
        observe: Existing selection fixture.
        path: Original history path.
        today: Effective date override.
        random: Caller-owned random source.
        progress: Original presenter.
    """

    observe: Callable[..., blast.BlastFromPastBatch]
    path: Path
    today: date | None
    random: blast.RandomIndexReader
    progress: blast.ProgressCallback | None

    def run(self, count: int) -> blast.BlastFromPastBatch:
        """Observe selection when execution requests its original open slots.

        Args:
            count: Requested open slots.

        Returns:
            The fixture's original batch.
        """
        return self.observe(
            count=count,
            path=self.path,
            today=self.today,
            random_index_reader=self.random,
            progress_callback=self.progress,
        )


@dataclass(frozen=True)
class ObservedRadioSelection:
    """Bind an existing anniversary oracle to the concrete selection boundary.

    Args:
        observe: Existing selection fixture.
        path: Original history path.
        today: Effective date override.
        random: Caller-owned timestamp source.
        progress: Original presenter.

    """

    observe: Callable[..., radio.DailyMindRadioBatch]
    path: Path
    today: date | None
    random: radio.RandomTimestampReader
    progress: blast.ProgressCallback | None

    def run(self) -> radio.DailyMindRadioBatch:
        """Observe anniversary selection when execution reaches that boundary.

        Returns:
            The fixture's original batch.
        """
        return self.observe(
            path=self.path,
            today=self.today,
            random_timestamp_reader=self.random,
            progress_callback=self.progress,
        )


def dormant_track(
    workflow: DormantLikedTrack,
    observe: Callable[..., CatalogTrack | None],
    artist_id: str,
) -> CatalogTrack | None:
    """Observe the same liked-track fixture through the resource method.

    Args:
        resources: Caller-owned dormant resources.
        observe: Existing liked-track fixture.
        artist_id: Mapped artist identity.

    Returns:
        The fixture's preferred track, if any.
    """
    resources = cast(LegacyDormantCatalog, workflow.catalog)
    return observe(resources.spotify, artist_id, resources.retry)


def catalog(
    resources: DiscographyCatalog,
    observe: Callable[..., tuple[CatalogRelease, ...]],
    artist: str,
) -> tuple[CatalogRelease, ...]:
    """Retain the original catalog oracle's client and retry arguments.

    Args:
        resources: Named catalog application stage.
        observe: Existing scripted catalog boundary.
        artist: Original requested Spotify identity.

    Returns:
        Original ordered catalog facts.
    """
    source = cast(DiscographySpotify, resources.source)
    return observe(source.spotify, artist, source.retry)


def historical_artist(
    resources: DiscographyHistory,
    observe: Callable[..., HistoricalArtistSelection],
) -> HistoricalArtistSelection:
    """Retain the original history oracle's observation context.

    Args:
        resources: Named historical-selection application stage.
        observe: Existing scripted history boundary.

    Returns:
        Original complete historical selection.
    """
    source = cast(LegacyDatedHistory, resources.source)
    return observe(
        path=source.path,
        today=source.date_override,
        random_index_reader=source.index_reader,
        progress_callback=resources.progress,
    )


def resolve_artist(
    resources: DiscographyArtistMapping,
    observe: Callable[..., QueueArtist],
    selection: HistoricalArtistSelection,
) -> QueueArtist:
    """Retain the original mapping oracle's complete context.

    Args:
        resources: Named historical artist-mapping application stage.
        observe: Existing scripted mapping boundary.
        selection: Original complete historical facts.

    Returns:
        Original accepted Memory Lane candidate.
    """
    source = cast(DiscographyArtistCatalog, resources.catalog)
    return observe(source.spotify, selection, source.choice, source.retry)


def audit(
    resources: LegacyRecommendationRun,
    observe: Callable[..., None],
    summary: found_art.FoundArtSummary,
) -> None:
    """Observe the original audit callback through recommendation resources.

    Args:
        resources: Caller-owned recommendation resources.
        observe: Existing audit observer.
        summary: Original completed summary.
    """
    observe(summary, resources.log_path)
