"""Rank actual album listening while keeping unavailable artwork in the quilt."""

import unicodedata
from collections import Counter
from datetime import datetime
from datetime import timedelta

from spotify_manager.domain.listening_cover_values import CoverCatalog
from spotify_manager.domain.listening_cover_values import CoverEvidence
from spotify_manager.domain.listening_cover_values import ListeningQuilt
from spotify_manager.domain.listening_cover_values import QuiltAlbum
from spotify_manager.domain.listening_cover_values import QuiltCoverage
from spotify_manager.domain.listening_cover_values import QuiltOptions
from spotify_manager.domain.listening_cover_values import QuiltOutcome
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import ListeningCounts
from spotify_manager.domain.listening_values import RankedEntity


EVIDENCE: tuple[CoverEvidence, ...] = (
    "ready",
    "no_cover",
    "unmatched",
    "ambiguous",
    "incomplete",
    "missing",
)


def _order(item: QuiltAlbum) -> tuple[int, str, str, str]:
    return (
        -item.album.plays,
        item.album.name.casefold(),
        item.album.artist.casefold(),
        item.album.key,
    )


def _albums(
    lifetimes: tuple[EntityLifetime, ...], catalog: CoverCatalog
) -> tuple[QuiltAlbum, ...]:
    metadata = {item.album_key: item for item in catalog.entries}
    total = sum(item.plays for item in lifetimes)
    result = []
    for item in lifetimes:
        source = metadata.get(item.key)
        album = RankedEntity(
            item.key,
            item.name,
            item.artist,
            item.plays,
            item.plays / total if total else 0,
        )
        result.append(
            QuiltAlbum(
                album,
                source.state if source else "missing",
                source.candidates if source else (),
                source.candidate_count if source else 0,
                source.fetched_at if source else None,
                source.artwork if source else None,
            )
        )
    return tuple(sorted(result, key=_order))


def _included(item: QuiltAlbum, search: str) -> bool:
    value = unicodedata.normalize(
        "NFC", item.album.name + " " + item.album.artist
    ).casefold()
    return unicodedata.normalize("NFC", search.strip()).casefold() in value


def _outcomes(items: tuple[QuiltAlbum, ...]) -> tuple[QuiltOutcome, ...]:
    albums: Counter[CoverEvidence] = Counter()
    plays: Counter[CoverEvidence] = Counter()
    for item in items:
        albums[item.evidence] += 1
        plays[item.evidence] += item.album.plays
    return tuple(QuiltOutcome(key, albums[key], plays[key]) for key in EVIDENCE)


def get_quilt_analysis(
    lifetimes: tuple[EntityLifetime, ...],
    counts: ListeningCounts,
    catalog: CoverCatalog,
    options: QuiltOptions,
) -> ListeningQuilt:
    """Build a deterministic top-album quilt without dropping unavailable images.

    Args:
        lifetimes: Named-album counts for one complete selected history.
        counts: Whole-selection counts, including missing album names.
        catalog: Independently pinned current cover evidence and bytes.
        options: Bounded size and optional album/artist search.

    Returns:
        Ranked tiles with exact scope, residual listening and artwork outcomes.
    """
    albums = _albums(lifetimes, catalog)
    matching = tuple(item for item in albums if _included(item, options.search))
    shown = matching[: options.size]
    outcomes = _outcomes(shown)
    dates = [item.fetched_at for item in shown if item.fetched_at]
    ready = outcomes[0]
    coverage = QuiltCoverage(
        counts.scrobbles,
        sum(item.plays for item in lifetimes),
        counts.missing_album,
        len(albums),
        len(matching),
        sum(item.album.plays for item in shown),
        ready.albums,
        ready.plays,
        outcomes,
    )
    return ListeningQuilt(
        catalog.snapshot,
        shown,
        options,
        coverage,
        min(dates) if dates else None,
        max(dates) if dates else None,
    )


def cover_fetch_candidates(
    items: tuple[QuiltAlbum, ...], now: datetime, limit: int, force: bool
) -> tuple[RankedEntity, ...]:
    """Capture highest-ranked missing/stale names from only the displayed quilt.

    Args:
        items: Visible ranked album identities from one pinned selection.
        now: Explicit aware freshness instant.
        limit: Validated maximum number of albums.
        force: Include recently cached observations.

    Returns:
        At most ten album/artist names; no play counts are sent to the provider.
    """
    result = []
    for item in items:
        fresh = item.fetched_at and now - datetime.fromisoformat(
            item.fetched_at
        ) < timedelta(days=30)
        if force or not fresh:
            result.append(item.album)
        if len(result) == limit:
            break
    return tuple(result)
