"""Assemble an ordered playlist proposal from pinned listening and liked tracks."""

from dataclasses import dataclass
from dataclasses import replace
from typing import Literal

from spotify_manager.domain.listening_library_values import LibraryCatalog
from spotify_manager.domain.listening_library_values import LibraryEntry
from spotify_manager.domain.listening_library_values import MirrorSource


type PlaylistEvidence = Literal["exact_name", "reviewed"]
type UnresolvedReason = Literal[
    "unmatched", "ambiguous", "publication_unavailable", "review_unavailable"
]
type PlaylistView = Literal["tracks", "duplicates", "unresolved"]


@dataclass(frozen=True)
class RecordedTrack:
    """Keep one recorded track and its selected plays and earliest observation."""

    key: str
    name: str
    artist: str
    plays: int
    first_ms: int


@dataclass(frozen=True)
class PlaylistReview:
    """Carry one browser-confirmed history key and a candidate Spotify URI."""

    key: str
    uri: str


@dataclass(frozen=True)
class PlaylistTrack:
    """Keep one proposed Spotify track and the evidence for its first appearance."""

    position: int
    track: LibraryEntry
    history: RecordedTrack
    evidence: PlaylistEvidence
    plays: int


@dataclass(frozen=True)
class PlaylistUnresolved:
    """Retain a recorded track whose plays lack one usable Spotify candidate."""

    history: RecordedTrack
    reason: UnresolvedReason
    candidate_count: int


@dataclass(frozen=True)
class PlaylistSummary:
    """Reconcile selected plays across first matches, repeats, and unresolved plays."""

    selected_plays: int
    playlist_tracks: int
    duplicate_plays: int
    unresolved_tracks: int
    unresolved_plays: int


@dataclass(frozen=True)
class PlaylistPreview:
    """Keep complete private evidence for pagination and the full proposal CSV."""

    library_snapshot: str
    source: MirrorSource
    summary: PlaylistSummary
    tracks: tuple[PlaylistTrack, ...]
    unresolved: tuple[PlaylistUnresolved, ...]


@dataclass(frozen=True)
class PlaylistOptions:
    """Select a bounded page of the proposal or its supporting evidence."""

    view: PlaylistView
    page: int
    limit: int


@dataclass(frozen=True)
class PlaylistPage:
    """Present exact summary totals and a bounded evidence page."""

    library_snapshot: str
    source: MirrorSource
    summary: PlaylistSummary
    items: tuple[PlaylistTrack | PlaylistUnresolved, ...]
    total: int
    options: PlaylistOptions


@dataclass(frozen=True)
class _TrackCandidates:
    source: MirrorSource
    by_name: dict[str, dict[str, LibraryEntry]]
    by_uri: dict[str, LibraryEntry]


def _track_candidates(catalog: LibraryCatalog) -> _TrackCandidates:
    source = next(item for item in catalog.sources if item.kind == "track")
    by_name: dict[str, dict[str, LibraryEntry]] = {}
    by_uri: dict[str, LibraryEntry] = {}
    for entry in catalog.entries:
        if entry.kind == "track":
            by_name.setdefault(entry.key, {})[entry.uri] = entry
            by_uri.setdefault(entry.uri, entry)
    return _TrackCandidates(source, by_name, by_uri)


def _reviewed_track(
    history: RecordedTrack, candidates: _TrackCandidates, uri: str
) -> PlaylistTrack | PlaylistUnresolved:
    reviewed = candidates.by_uri.get(uri)
    if reviewed is None:
        return PlaylistUnresolved(history, "review_unavailable", 0)
    return PlaylistTrack(0, reviewed, history, "reviewed", history.plays)


def _resolve(
    history: RecordedTrack, candidates: _TrackCandidates, review: str | None
) -> PlaylistTrack | PlaylistUnresolved:
    if candidates.source.state != "ready":
        return PlaylistUnresolved(history, "publication_unavailable", 0)
    if review is not None:
        return _reviewed_track(history, candidates, review)
    matches = candidates.by_name.get(history.key, {})
    if len(matches) == 1:
        return PlaylistTrack(
            0, next(iter(matches.values())), history, "exact_name", history.plays
        )
    reason: UnresolvedReason = "ambiguous" if matches else "unmatched"
    return PlaylistUnresolved(history, reason, len(matches))


def _add_track(tracks: dict[str, PlaylistTrack], item: PlaylistTrack) -> None:
    uri = item.track.uri
    previous = tracks.get(uri)
    if previous is not None:
        tracks[uri] = replace(previous, plays=previous.plays + item.plays)
        return
    tracks[uri] = replace(item, position=len(tracks) + 1)


def build_playlist_preview(
    history: tuple[RecordedTrack, ...],
    catalog: LibraryCatalog,
    reviews: tuple[PlaylistReview, ...],
) -> PlaylistPreview:
    """Propose unique liked-track URIs in first selected recorded order.

    Args:
        history: Selected track groups ordered by their first play and source row.
        catalog: Pinned complete mirror evidence and source availability.
        reviews: Explicit browser choices to recheck against the pinned mirror.

    Returns:
        An ordered proposal and all unresolved records grouped by recorded identity.
    """
    candidates = _track_candidates(catalog)
    reviewed = {choice.key: choice.uri for choice in reviews}
    tracks: dict[str, PlaylistTrack] = {}
    unresolved: list[PlaylistUnresolved] = []
    for recorded in history:
        item = _resolve(recorded, candidates, reviewed.get(recorded.key))
        if isinstance(item, PlaylistUnresolved):
            unresolved.append(item)
        else:
            _add_track(tracks, item)
    matched_plays = sum(item.plays for item in tracks.values())
    unresolved_plays = sum(item.history.plays for item in unresolved)
    summary = PlaylistSummary(
        matched_plays + unresolved_plays,
        len(tracks),
        matched_plays - len(tracks),
        len(unresolved),
        unresolved_plays,
    )
    return PlaylistPreview(
        catalog.snapshot,
        candidates.source,
        summary,
        tuple(tracks.values()),
        tuple(unresolved),
    )


def page_playlist(preview: PlaylistPreview, options: PlaylistOptions) -> PlaylistPage:
    """Page the chosen evidence while keeping the full proposal totals.

    Args:
        preview: Complete proposal for one immutable source pair and selection.
        options: Applied view and pagination bounds.

    Returns:
        One bounded page and exact counts across the selected history.
    """
    items: tuple[PlaylistTrack | PlaylistUnresolved, ...] = preview.tracks
    if options.view == "unresolved":
        items = preview.unresolved
    if options.view == "duplicates":
        items = tuple(item for item in preview.tracks if item.plays > 1)
    offset = (options.page - 1) * options.limit
    return PlaylistPage(
        preview.library_snapshot,
        preview.source,
        preview.summary,
        items[offset : offset + options.limit],
        len(items),
        options,
    )
