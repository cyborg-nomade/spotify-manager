"""Preserve observed callback arguments when fixtures inject explicit ports."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

from spotipy import Spotify

from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import HistoricalArtistSelection
from spotify_manager.domain.discography_values import QueueArtist
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.infrastructure.legacy.dormant_artists import LegacyDormantRecovery
from spotify_manager.infrastructure.legacy.recommendations import (
    LegacyRecommendationRun,
)
from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import daily_mind_radio as radio
from spotify_manager.routines import discography
from spotify_manager.routines import found_art


def blast_batch(
    observe: Callable[..., blast.BlastFromPastBatch],
    path: Path,
    today: date | None,
    random: blast.RandomIndexReader,
    progress: blast.ProgressCallback | None,
    count: int,
) -> blast.BlastFromPastBatch:
    """Call the original observed selection with its keyword arguments.

    Args:
        observe: Existing selection fixture.
        path: Original history path.
        today: Effective date override.
        random: Caller-owned random source.
        progress: Original presenter.
        count: Requested open slots.

    Returns:
        The fixture's original batch.
    """
    return observe(
        count=count,
        path=path,
        today=today,
        random_index_reader=random,
        progress_callback=progress,
    )


def radio_batch(
    observe: Callable[..., radio.DailyMindRadioBatch],
    path: Path,
    today: date | None,
    random: radio.RandomTimestampReader,
    progress: blast.ProgressCallback | None,
) -> radio.DailyMindRadioBatch:
    """Call the observed anniversary selection with its original arguments.

    Args:
        observe: Existing selection fixture.
        path: Original history path.
        today: Effective date override.
        random: Caller-owned timestamp source.
        progress: Original presenter.

    Returns:
        The fixture's original batch.
    """
    return observe(
        path=path,
        today=today,
        random_timestamp_reader=random,
        progress_callback=progress,
    )


def dormant_track(
    resources: LegacyDormantRecovery,
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
    return observe(resources.spotify, artist_id, resources.retry)


def catalog(
    observe: Callable[..., tuple[CatalogRelease, ...]],
    spotify: Spotify,
    retry: discography.RetryCall,
    candidate: QueueArtist,
) -> tuple[CatalogRelease, ...]:
    """Preserve catalog fixture arguments through direct planning reads.

    Args:
        observe: Existing catalog fixture.
        spotify: Caller-owned client.
        retry: Caller-owned retry policy.
        candidate: Original queue candidate.

    Returns:
        The fixture's original ordered releases.
    """
    return observe(spotify, candidate.spotify_id, retry)


def historical_artist(
    observe: Callable[..., HistoricalArtistSelection],
    path: Path,
    today: date | None,
    random: discography.RandomIndexReader,
    progress: discography.ProgressCallback | None,
) -> HistoricalArtistSelection:
    """Preserve the historical fixture's original keyword arguments.

    Args:
        observe: Existing historical selection fixture.
        path: Original export path.
        today: Effective date override.
        random: Caller-owned random source.
        progress: Original presenter.

    Returns:
        The fixture's original historical selection.
    """
    return observe(
        path=path, today=today, random_index_reader=random, progress_callback=progress
    )


def resolve_artist(
    observe: Callable[..., QueueArtist],
    spotify: Spotify,
    choice: discography.HistoricalArtistChoiceReader | None,
    retry: discography.RetryCall,
    selection: HistoricalArtistSelection,
) -> QueueArtist:
    """Preserve the historical mapping fixture's original argument order.

    Args:
        observe: Existing mapping fixture.
        spotify: Caller-owned client.
        choice: Original mapping interaction.
        retry: Caller-owned retry policy.
        selection: Original historical selection.

    Returns:
        The fixture's original mapped queue artist.
    """
    return observe(spotify, selection, choice, retry)


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
