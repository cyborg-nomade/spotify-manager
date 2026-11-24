"""Conservative name evidence against independently published collections."""

import unicodedata

from spotify_manager.domain.listening_library_values import LibraryCandidateOptions
from spotify_manager.domain.listening_library_values import LibraryCandidatePage
from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import LibraryComparison
from spotify_manager.domain.listening_library_values import LibraryComparisonItem
from spotify_manager.domain.listening_library_values import LibraryCoverage
from spotify_manager.domain.listening_library_values import LibraryEntry
from spotify_manager.domain.listening_library_values import LibraryMatch
from spotify_manager.domain.listening_library_values import LibraryOptions
from spotify_manager.domain.listening_library_values import LibraryReviewCandidate
from spotify_manager.domain.listening_library_values import MirrorSource
from spotify_manager.domain.listening_values import EntityKind
from spotify_manager.domain.listening_values import EntityLifetime


MATCH_STATES: tuple[LibraryMatch, ...] = (
    "name_match",
    "unmatched",
    "ambiguous",
    "unavailable",
)


def _evidence(
    item: EntityLifetime, candidates: tuple[LibraryEntry, ...], ready: bool
) -> LibraryComparisonItem:
    if not ready:
        return LibraryComparisonItem(item, "unavailable", (), 0)
    if not candidates:
        return LibraryComparisonItem(item, "unmatched", (), 0)
    status: LibraryMatch = "name_match" if len(candidates) == 1 else "ambiguous"
    return LibraryComparisonItem(item, status, candidates[:5], len(candidates))


def _entry_index(
    catalog: LibraryCatalog, options: LibraryOptions
) -> dict[str, tuple[LibraryEntry, ...]]:
    groups: dict[str, dict[str, LibraryEntry]] = {}
    for entry in catalog.entries:
        if entry.kind == options.kind:
            groups.setdefault(entry.key, {})[entry.uri] = entry
    result = {}
    for key, entries in groups.items():
        result[key] = tuple(entries[uri] for uri in sorted(entries))
    return result


def _coverage(items: list[LibraryComparisonItem]) -> tuple[LibraryCoverage, ...]:
    entities: dict[LibraryMatch, int] = dict.fromkeys(MATCH_STATES, 0)
    plays: dict[LibraryMatch, int] = dict.fromkeys(MATCH_STATES, 0)
    for item in items:
        entities[item.status] += 1
        plays[item.status] += item.history.plays
    result = []
    for state in MATCH_STATES:
        result.append(LibraryCoverage(state, entities[state], plays[state]))
    return tuple(result)


def _included(item: LibraryComparisonItem, options: LibraryOptions) -> bool:
    if options.status != "all" and options.status != item.status:
        return False
    text = item.history.name + " " + item.history.artist
    normalized = unicodedata.normalize("NFC", text).casefold()
    search = unicodedata.normalize("NFC", options.search.strip()).casefold()
    return search in normalized


def _item_order(item: LibraryComparisonItem) -> tuple[int, str, str]:
    return -item.history.plays, item.history.name.casefold(), item.history.key


def _collection(catalog: LibraryCatalog, kind: EntityKind) -> MirrorSource:
    return next(item for item in catalog.sources if item.kind == kind)


def compare_library(
    history: tuple[EntityLifetime, ...],
    catalog: LibraryCatalog,
    options: LibraryOptions,
) -> LibraryComparison:
    """Compare exact normalized names without claiming resolved music identity.

    Args:
        history: Exact selected recorded entities; missing albums stay excluded.
        catalog: Verified current publications, possibly with unavailable sources.
        options: Evidence/search filters and bounded pagination.

    Returns:
        Reconciled category counts and a page preserving all match candidates.
    """
    source = _collection(catalog, options.kind)
    entries = _entry_index(catalog, options)
    items = []
    for entity in history:
        if entity.plays >= options.minimum_plays:
            items.append(
                _evidence(entity, entries.get(entity.key, ()), source.state == "ready")
            )
    coverage = _coverage(items)
    selected = [item for item in items if _included(item, options)]
    selected.sort(key=_item_order)
    offset = (options.page - 1) * options.limit
    page = tuple(selected[offset : offset + options.limit])
    return LibraryComparison(
        catalog.snapshot,
        catalog.revision,
        source,
        coverage,
        page,
        len(selected),
        options.page,
        options.limit,
        options,
    )


def _review_matches(entry: LibraryEntry, history: EntityLifetime, term: str) -> bool:
    if not term:
        return entry.key == history.key
    if term.casefold().startswith("spotify:"):
        return entry.uri == term
    text = unicodedata.normalize("NFC", entry.name + " " + entry.artist).casefold()
    words = unicodedata.normalize("NFC", term).casefold().split()
    return all(word in text for word in words)


def _review_order(candidate: LibraryReviewCandidate) -> tuple[bool, str, str, str]:
    entry = candidate.entry
    return (
        not candidate.exact_name,
        entry.name.casefold(),
        entry.artist.casefold(),
        entry.uri,
    )


def _review_candidates(
    history: EntityLifetime, catalog: LibraryCatalog, options: LibraryCandidateOptions
) -> list[LibraryReviewCandidate]:
    candidates: dict[str, LibraryReviewCandidate] = {}
    term = options.search.strip()
    for entry in catalog.entries:
        if entry.kind != options.selection.kind or not _review_matches(
            entry, history, term
        ):
            continue
        candidates[entry.uri] = LibraryReviewCandidate(entry, entry.key == history.key)
    return sorted(candidates.values(), key=_review_order)


def review_library_candidates(
    history: EntityLifetime, catalog: LibraryCatalog, options: LibraryCandidateOptions
) -> LibraryCandidatePage:
    """Find published mirror entries for an explicit human match review.

    Args:
        history: Verified original history identity selected by the listener.
        catalog: Immutable set of published Spotify mirrors.
        options: Collection, search and pagination bounds.

    Returns:
        A page of candidate evidence with the source availability preserved.
    """
    source = _collection(catalog, options.selection.kind)
    candidates = (
        _review_candidates(history, catalog, options) if source.state == "ready" else []
    )
    offset = (options.page - 1) * options.limit
    return LibraryCandidatePage(
        catalog.snapshot,
        history,
        source,
        tuple(candidates[offset : offset + options.limit]),
        len(candidates),
        options.page,
        options.limit,
    )
