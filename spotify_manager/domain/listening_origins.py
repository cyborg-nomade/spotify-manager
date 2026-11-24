"""Conservative country associations from complete current name evidence."""

import unicodedata
from collections import Counter
from datetime import datetime
from datetime import timedelta

from spotify_manager.domain.listening_origin_values import ArtistOriginMetadata
from spotify_manager.domain.listening_origin_values import CountryListening
from spotify_manager.domain.listening_origin_values import ListeningOrigins
from spotify_manager.domain.listening_origin_values import OriginArtist
from spotify_manager.domain.listening_origin_values import OriginCatalog
from spotify_manager.domain.listening_origin_values import OriginCoverage
from spotify_manager.domain.listening_origin_values import OriginEvidence
from spotify_manager.domain.listening_origin_values import OriginOptions
from spotify_manager.domain.listening_origin_values import OriginOutcome
from spotify_manager.domain.listening_values import EntityLifetime
from spotify_manager.domain.listening_values import RankedEntity


EVIDENCE: tuple[OriginEvidence, ...] = (
    "single_country",
    "multiple_countries",
    "no_country",
    "unmatched",
    "ambiguous",
    "incomplete",
    "missing",
)
NON_GEOGRAPHIC_CODES = frozenset({"XW", "XE"})


def origin_evidence(metadata: ArtistOriginMetadata | None) -> OriginEvidence:
    """Select geographic evidence without treating a name candidate as identity.

    Args:
        metadata: Current bounded lookup or no observation.

    Returns:
        Exact evidence category; multiple countries never get arbitrary weights.
    """
    if metadata is None:
        return "missing"
    if metadata.state != "matched":
        return metadata.state
    countries = metadata.candidates[0].countries
    if len(countries) > 1:
        return "multiple_countries"
    if not countries or countries[0] in NON_GEOGRAPHIC_CODES:
        return "no_country"
    return "single_country"


def _artist_order(item: OriginArtist) -> tuple[int, str, str]:
    return -item.artist.plays, item.artist.name.casefold(), item.artist.key


def _artists(
    lifetimes: tuple[EntityLifetime, ...], catalog: OriginCatalog
) -> tuple[OriginArtist, ...]:
    metadata = {item.artist_key: item for item in catalog.entries}
    total = sum(item.plays for item in lifetimes)
    result = []
    for item in lifetimes:
        source = metadata.get(item.key)
        artist = RankedEntity(
            item.key, item.name, "", item.plays, item.plays / total if total else 0
        )
        result.append(
            OriginArtist(
                artist,
                origin_evidence(source),
                source.candidates if source else (),
                source.candidate_count if source else 0,
                source.fetched_at if source else None,
            )
        )
    return tuple(sorted(result, key=_artist_order))


def _coverage(items: tuple[OriginArtist, ...]) -> OriginCoverage:
    plays: Counter[OriginEvidence] = Counter()
    artists: Counter[OriginEvidence] = Counter()
    for item in items:
        plays[item.evidence] += item.artist.plays
        artists[item.evidence] += 1
    outcomes = tuple(OriginOutcome(key, artists[key], plays[key]) for key in EVIDENCE)
    return OriginCoverage(
        plays.total(),
        len(items),
        plays["single_country"],
        artists["single_country"],
        len(items) - artists["missing"],
        outcomes,
    )


def _countries(items: tuple[OriginArtist, ...]) -> tuple[CountryListening, ...]:
    plays: Counter[str] = Counter()
    artists: Counter[str] = Counter()
    total = sum(item.artist.plays for item in items)
    for item in items:
        if item.evidence != "single_country":
            continue
        code = item.candidates[0].countries[0]
        plays[code] += item.artist.plays
        artists[code] += 1
    result = []
    for code, count in sorted(plays.items(), key=_country_order):
        result.append(
            CountryListening(code, count, artists[code], count / total if total else 0)
        )
    return tuple(result)


def _country_order(item: tuple[str, int]) -> tuple[int, str]:
    return -item[1], item[0]


def _included(item: OriginArtist, options: OriginOptions) -> bool:
    name = unicodedata.normalize("NFC", item.artist.name).casefold()
    search = unicodedata.normalize("NFC", options.search.strip()).casefold()
    if search not in name:
        return False
    if options.evidence != "all" and options.evidence != item.evidence:
        return False
    if options.country is None:
        return True
    return any(options.country in candidate.countries for candidate in item.candidates)


def _artist_codes(item: OriginArtist) -> set[str]:
    codes: set[str] = set()
    for candidate in item.candidates:
        codes.update(candidate.countries)
    return codes


def _available_countries(items: tuple[OriginArtist, ...]) -> tuple[str, ...]:
    codes: set[str] = set()
    for item in items:
        codes.update(_artist_codes(item))
    return tuple(sorted(codes))


def get_origin_analysis(
    lifetimes: tuple[EntityLifetime, ...],
    catalog: OriginCatalog,
    options: OriginOptions,
) -> ListeningOrigins:
    """Count complete country evidence before filtering a supporting artist page.

    Args:
        lifetimes: Actual artist counts for one validated history selection.
        catalog: Complete independently pinned geographic metadata.
        options: Bounded evidence, country and search filters.

    Returns:
        Country totals, explicit residual coverage and a supporting artist page.
    """
    artists = _artists(lifetimes, catalog)
    selected = tuple(item for item in artists if _included(item, options))
    dates = [item.fetched_at for item in artists if item.fetched_at]
    offset = (options.page - 1) * options.limit
    return ListeningOrigins(
        catalog.snapshot,
        _countries(artists),
        _available_countries(artists),
        _coverage(artists),
        selected[offset : offset + options.limit],
        len(selected),
        options.page,
        options.limit,
        options,
        min(dates) if dates else None,
        max(dates) if dates else None,
    )


def origin_fetch_candidates(
    lifetimes: tuple[EntityLifetime, ...],
    catalog: OriginCatalog,
    now: datetime,
    limit: int,
    force: bool,
) -> tuple[RankedEntity, ...]:
    """Select at most twenty-five highest-play missing or thirty-day-old artists.

    Args:
        lifetimes: Actual selected artist counts.
        catalog: Current lookup outcomes.
        now: Explicit aware freshness instant.
        limit: Positive HTTP-validated batch bound.
        force: Include recently cached results.

    Returns:
        Deterministic captured names; this decision performs no external reads.
    """
    result = []
    for item in _artists(lifetimes, catalog):
        fresh = item.fetched_at and now - datetime.fromisoformat(
            item.fetched_at
        ) < timedelta(days=30)
        if force or not fresh:
            result.append(item.artist)
        if len(result) == limit:
            break
    return tuple(result)


def origin_backfill_candidates(
    lifetimes: tuple[EntityLifetime, ...], catalog: OriginCatalog, limit: int
) -> tuple[RankedEntity, ...]:
    """Choose never-looked-up artists from full history in highest-play order.

    Args:
        lifetimes: Artist counts from one complete history generation.
        catalog: Completed outcomes, including unresolved candidates.
        limit: Maximum missing artists to queue.

    Returns:
        Deterministic next artists for the full loader or nightly catch-up.
    """
    result = []
    for item in _artists(lifetimes, catalog):
        if item.evidence != "missing":
            continue
        result.append(item.artist)
        if len(result) == limit:
            break
    return tuple(result)
