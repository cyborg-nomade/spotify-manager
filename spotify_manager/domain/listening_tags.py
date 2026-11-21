"""Allocate recorded plays to current community labels with explicit unknowns."""

import unicodedata
from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta

from spotify_manager.domain.listening_tag_values import ArtistTagMetadata
from spotify_manager.domain.listening_tag_values import ListeningTags
from spotify_manager.domain.listening_tag_values import TagAnalysis
from spotify_manager.domain.listening_tag_values import TagArtist
from spotify_manager.domain.listening_tag_values import TagCatalog
from spotify_manager.domain.listening_tag_values import TagCoverage
from spotify_manager.domain.listening_tag_values import TagOptions
from spotify_manager.domain.listening_tag_values import TagSeries
from spotify_manager.domain.listening_time import bucket_names
from spotify_manager.domain.listening_time import local_instant
from spotify_manager.domain.listening_values import ArtistPlay
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import ListeningQuery
from spotify_manager.domain.listening_values import RankedEntity


@dataclass
class _TagCounts:
    periods: dict[str, dict[str, float]] = field(default_factory=dict)
    totals: dict[str, float] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)

    def allocate(
        self, period: str, plays: int, metadata: ArtistTagMetadata | None, size: int
    ) -> None:
        tags = metadata.tags[:size] if metadata and metadata.state == "tagged" else ()
        counts = self.periods.setdefault(period, {})
        if not tags:
            counts["unknown"] = counts.get("unknown", 0.0) + plays
            return
        for tag in tags:
            counts[tag.key] = counts.get(tag.key, 0.0) + plays / len(tags)
            self.totals[tag.key] = self.totals.get(tag.key, 0.0) + plays / len(tags)
            self.names[tag.key] = tag.name

    def series(self, periods: tuple[str, ...]) -> tuple[TagSeries, ...]:
        ranked = sorted(self.totals.items(), key=_tag_order)
        selected = tuple(key for key, _count in ranked[:8])
        result = []
        for key in selected:
            values = self._values(periods, key)
            result.append(TagSeries(key, self.names[key], values))
        result.append(TagSeries("other", "Other tags", self._other(periods, selected)))
        unknown = self._values(periods, "unknown")
        result.append(TagSeries("unknown", "Unknown / no tags", unknown))
        return tuple(result)

    def _values(self, periods: tuple[str, ...], key: str) -> tuple[float, ...]:
        result = []
        for period in periods:
            result.append(self.periods.get(period, {}).get(key, 0.0))
        return tuple(result)

    def _other(
        self, periods: tuple[str, ...], selected: tuple[str, ...]
    ) -> tuple[float, ...]:
        result = []
        for period in periods:
            result.append(_residual(self.periods.get(period, {}), selected))
        return tuple(result)


def _tag_order(item: tuple[str, float]) -> tuple[float, str]:
    return -item[1], item[0]


def _residual(counts: dict[str, float], selected: tuple[str, ...]) -> float:
    total = 0.0
    for key, value in counts.items():
        if key not in selected and key != "unknown":
            total += value
    return total


def _artist_evidence(
    lifetimes: tuple[EntityLifetime, ...], metadata: dict[str, ArtistTagMetadata]
) -> tuple[TagArtist, ...]:
    total = sum(item.plays for item in lifetimes)
    result = []
    for item in lifetimes:
        source = metadata.get(item.key)
        artist = RankedEntity(
            item.key, item.name, "", item.plays, item.plays / total if total else 0
        )
        result.append(
            TagArtist(
                artist,
                source.state if source else "missing",
                source.tags if source else (),
                source.fetched_at if source else None,
                source.source_url if source else None,
            )
        )
    return tuple(sorted(result, key=_artist_order))


def _artist_order(item: TagArtist) -> tuple[int, str, str]:
    return -item.artist.plays, item.artist.name.casefold(), item.artist.key


def _coverage(items: tuple[TagArtist, ...]) -> TagCoverage:
    plays = sum(item.artist.plays for item in items)
    tagged = tuple(item for item in items if item.state == "tagged" and item.tags)
    return TagCoverage(
        plays,
        sum(item.artist.plays for item in tagged),
        len(items),
        len(tagged),
        sum(item.state != "missing" for item in items),
        sum(item.state == "empty" for item in items),
        sum(item.state == "unresolved" for item in items),
    )


def analyze_tags(
    plays: tuple[ArtistPlay, ...],
    lifetimes: tuple[EntityLifetime, ...],
    catalog: TagCatalog,
    query: ListeningQuery,
    per_artist: int,
) -> TagAnalysis:
    """Apply currently available labels without claiming historical tag knowledge.

    Args:
        plays: Exact filtered observations.
        lifetimes: Selected artist counts for bounded supporting evidence.
        catalog: One immutable cached metadata generation.
        query: Effective local calendar selection.
        per_artist: Leading tag or equal allocation among up to three tags.

    Returns:
        Complete monthly allocations and independent source-coverage counts.
    """
    metadata = {item.artist_key: item for item in catalog.entries}
    grouped: Counter[tuple[str, str]] = Counter()
    for play in plays:
        period = local_instant(play.timestamp_ms, query.timezone).strftime("%Y-%m")
        grouped[(period, play.artist_key)] += 1
    counts = _TagCounts()
    for (period, key), total in sorted(grouped.items()):
        counts.allocate(period, total, metadata.get(key), per_artist)
    periods = bucket_names(query, "month")
    artists = _artist_evidence(lifetimes, metadata)
    return TagAnalysis(periods, counts.series(periods), artists, _coverage(artists))


def _included(item: TagArtist, options: TagOptions, visible: set[str]) -> bool:
    name = unicodedata.normalize("NFC", item.artist.name).casefold()
    search = unicodedata.normalize("NFC", options.search.strip()).casefold()
    if search not in name:
        return False
    if options.tag == "unknown":
        return not item.tags or item.state != "tagged"
    if options.tag is None:
        return True
    if options.tag == "other":
        return any(tag.key not in visible for tag in item.tags[: options.per_artist])
    return any(tag.key == options.tag for tag in item.tags[: options.per_artist])


def present_tags(
    analysis: TagAnalysis, catalog: TagCatalog, options: TagOptions
) -> ListeningTags:
    """Page evidence without changing the complete plotted allocation.

    Args:
        analysis: Complete selected-history allocations.
        catalog: Independently pinned metadata identity.
        options: Applied allocation mode and evidence filters.

    Returns:
        Bounded evidence with complete totals and source coverage.
    """
    visible = {series.key for series in analysis.series}
    selected = []
    for item in analysis.artists:
        if _included(item, options, visible):
            selected.append(item)
    items = tuple(selected)
    dates = [item.fetched_at for item in analysis.artists if item.fetched_at]
    offset = (options.page - 1) * options.limit
    page = items[offset : offset + options.limit]
    return ListeningTags(
        catalog.snapshot,
        analysis.periods,
        analysis.series,
        analysis.coverage,
        page,
        len(items),
        options.page,
        options.limit,
        options,
        min(dates) if dates else None,
        max(dates) if dates else None,
    )


def tag_fetch_candidates(
    artists: tuple[EntityLifetime, ...],
    catalog: TagCatalog,
    now: datetime,
    limit: int,
    force: bool,
) -> tuple[RankedEntity, ...]:
    """Select a bounded highest-play batch, skipping recent completed lookups.

    Args:
        artists: Exact selected-history artists.
        catalog: Current cached lookup outcomes.
        now: Explicit aware instant for a thirty-day freshness decision.
        limit: Maximum provider requests.
        force: Refresh cached metadata as well as missing/stale entries.

    Returns:
        Deterministically ordered artist names and identities for public lookups.
    """
    metadata = {item.artist_key: item for item in catalog.entries}
    ordered = _artist_evidence(artists, metadata)
    result = []
    for item in ordered:
        fresh = item.fetched_at and now - datetime.fromisoformat(
            item.fetched_at
        ) < timedelta(days=30)
        if force or not fresh:
            result.append(item.artist)
        if len(result) == limit:
            break
    return tuple(result)
