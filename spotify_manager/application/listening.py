"""Named read-only Listening Explorer use cases over explicit index resources."""

from dataclasses import replace
from datetime import timedelta
from functools import lru_cache
from typing import Literal

from spotify_manager.application.listening_ports import ListeningReads
from spotify_manager.domain.listening_activity import listening_activity
from spotify_manager.domain.listening_activity import summarize_listening
from spotify_manager.domain.listening_evolution import listening_evolution
from spotify_manager.domain.listening_insights import compare_listening
from spotify_manager.domain.listening_insights import forgotten_favorites
from spotify_manager.domain.listening_insights import listening_discoveries
from spotify_manager.domain.listening_values import EntitySelection
from spotify_manager.domain.listening_values import ListeningActivity
from spotify_manager.domain.listening_values import ListeningComparison
from spotify_manager.domain.listening_values import ListeningDiscoveries
from spotify_manager.domain.listening_values import ListeningEntity
from spotify_manager.domain.listening_values import ListeningEvolution
from spotify_manager.domain.listening_values import ListeningOverview
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import ListeningRanking
from spotify_manager.domain.listening_values import ListeningRecords
from spotify_manager.domain.listening_values import ListeningRediscovery
from spotify_manager.domain.listening_values import RankingOptions
from spotify_manager.domain.listening_values import RecordOptions
from spotify_manager.domain.listening_values import RediscoveryOptions


@lru_cache(maxsize=32)
def get_listening_overview(
    index: ListeningReads, query: ListeningQuery
) -> ListeningOverview:
    """Summarize a selection without reading any live music service.

    Args:
        index: One ready immutable history generation.
        query: Validated local date and artist/rhythm selection.

    Returns:
        Exact counts and explicitly labeled averages.
    """
    return summarize_listening(index.counts(query), query)


@lru_cache(maxsize=16)
def get_listening_activity(
    index: ListeningReads, query: ListeningQuery
) -> ListeningActivity:
    """Aggregate selected observations using source-wide coverage boundaries.

    Args:
        index: One ready immutable history generation.
        query: Local date and optional artist/rhythm selection.

    Returns:
        Calendar cells and weekly rhythm with actual covered-hour denominators.
    """
    coverage = index.metadata.first_ms, index.metadata.last_ms
    return listening_activity(index.timestamps(query), query, coverage)


@lru_cache(maxsize=32)
def get_listening_rankings(
    index: ListeningReads, query: ListeningQuery, options: RankingOptions
) -> ListeningRanking:
    """Explore a bounded ranking within the current selection.

    Args:
        index: Complete published history index.
        query: Shared filter selection.
        options: Entity dimension, search, ordering, and pagination.

    Returns:
        One ranked page and the total matching entity count.
    """
    return index.rankings(query, options)


@lru_cache(maxsize=16)
def get_listening_evolution(
    index: ListeningReads,
    query: ListeningQuery,
    grain: Literal["week", "month"] = "month",
) -> ListeningEvolution:
    """Keep the selected top artists fixed while comparing temporal buckets.

    Args:
        index: Complete published history index.
        query: Shared filter selection.
        grain: Monday-based weeks or calendar months.

    Returns:
        Artist counts, Other, and aligned concentration/breadth metrics.
    """
    return listening_evolution(index.artist_plays(query), query, grain)


@lru_cache(maxsize=16)
def get_listening_records(
    index: ListeningReads,
    query: ListeningQuery,
    options: RecordOptions,
) -> ListeningRecords:
    """Read a bounded page of the underlying recorded observations.

    Args:
        index: Complete published history index.
        query: Shared filters.
        options: Bounded record page and optional independent entity selection.

    Returns:
        Newest-first records with stable source-order ties.
    """
    return index.records(query, options)


@lru_cache(maxsize=16)
def get_listening_entity(
    index: ListeningReads, query: ListeningQuery, selection: EntitySelection
) -> ListeningEntity:
    """Join an entity's pre-cutoff lifetime facts to filtered detail views.

    Args:
        index: Complete published history index.
        query: Shared local date filters.
        selection: Entity opened independently of the global artist filter.

    Returns:
        Lifetime facts, selected counts, activity, records, and related tracks.

    Raises:
        ListeningEntityError: No selected entity exists before the cutoff.
    """
    counts = index.counts(query, selection)
    coverage = index.metadata.first_ms, index.metadata.last_ms
    activity = listening_activity(index.timestamps(query, selection), query, coverage)
    options = RankingOptions(kind="track")
    return ListeningEntity(
        selection.kind,
        index.entity_lifetime(query, selection),
        summarize_listening(counts, query),
        activity,
        index.records(query, RecordOptions(limit=25, selection=selection)),
        index.rankings(query, options, selection),
    )


@lru_cache(maxsize=16)
def get_listening_discoveries(
    index: ListeningReads, query: ListeningQuery
) -> ListeningDiscoveries:
    """Evaluate new-artist cohorts without resetting firsts at the visible start.

    Args:
        index: Complete published history index.
        query: Cohort dates, timezone, and optional artist selection.

    Returns:
        First-observed artist cohorts and complete follow-up denominators.
    """
    plays = index.artist_plays(query, full_history=True)
    return listening_discoveries(plays, query, index.metadata.last_ms)


@lru_cache(maxsize=16)
def get_listening_rediscovery(
    index: ListeningReads,
    query: ListeningQuery,
    options: RediscoveryOptions,
) -> ListeningRediscovery:
    """Find substantial favorites absent for a selected number of days.

    Args:
        index: Complete published history index.
        query: Analysis cutoff, timezone, and optional artist selection.
        options: Favorite dimension and minimum recorded-play/inactivity thresholds.

    Returns:
        Transparent pre-cutoff counts and gaps, capped at 100 favorites.
    """
    lifetimes = index.lifetimes(query, options.kind, full_history=True)
    return forgotten_favorites(
        lifetimes, query, (options.minimum_plays, options.minimum_gap)
    )


@lru_cache(maxsize=16)
def get_listening_comparison(
    index: ListeningReads, query: ListeningQuery
) -> ListeningComparison:
    """Compare the current selection to an equally long preceding period.

    Args:
        index: Complete published history index.
        query: Current period and shared filters.

    Returns:
        Counts/share changes and the earlier period's coverage indicator.
    """
    duration = timedelta(days=(query.end - query.start).days + 1)
    previous = replace(
        query, start=query.start - duration, end=query.start - timedelta(days=1)
    )
    periods = index.lifetimes(previous, "artist"), index.lifetimes(query, "artist")
    return compare_listening(periods, query, index.metadata.first_ms)
