"""Original playlist container parsing, identity projection and paging guards."""

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol
from typing import cast

from spotify_manager.application.historical_values import SpotifyTrackResolutionError
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.titles import without_sliding_qualifiers
from spotify_manager.infrastructure.history_matching_records import artist_names


@dataclass
class PlaylistObservations:
    """Accumulate original encountered playlist identities and continuation tokens.

    Args:
        offset: Original raw item count.
        ids: Original observed track identities.
        keys: Original normalized artist/title pairs.
        primary: Original normalized first-credit artists.
        seen: Original continuation tokens seen after accepted nonempty pages.
    """

    offset: int = 0
    ids: set[str] = field(default_factory=set)
    keys: set[tuple[str, str]] = field(default_factory=set)
    primary: set[str] = field(default_factory=set)
    seen: set[str] = field(default_factory=set)


class HistoryPlaylistPages(Protocol):
    """Read complete raw playlist pages at explicit offsets."""

    async def read(self, offset: int) -> object:
        """Read one transport page.

        Args:
            offset: Raw row offset.

        Returns:
            Unvalidated response.
        """
        ...


async def state(
    pages: HistoryPlaylistPages,
    playlist: str,
) -> PlaylistState:
    """Retain original raw offsets and explicit continuation precedence.

    Args:
        pages: Named page reader owning cancellation and retry boundaries.
        playlist: Original playlist used in visible errors.

    Returns:
        Original complete ordered-playlist membership projection.

    Raises:
        SpotifyTrackResolutionError: Original container or paging guard fails.
    """
    facts = PlaylistObservations()
    while True:
        page = _page((await pages.read(facts.offset)), playlist)
        rows = cast(list[object], page["items"])
        _collect(rows, facts)
        facts.offset += len(rows)
        if not _has_more(page, facts.offset):
            return _result(page, facts)
        _check_continuation(page.get("next"), rows, facts.seen, playlist)


def _page(raw: object, playlist: str) -> dict[str, object]:
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise SpotifyTrackResolutionError(
            f"Spotify returned invalid playlist data for {playlist}."
        )
    return cast(dict[str, object], raw)


def _collect(
    rows: list[object],
    facts: PlaylistObservations,
) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        track = row.get("item") or row.get("track")
        if isinstance(track, dict):
            _collect_track(track, facts)


def _collect_track(
    raw: dict[str, object],
    facts: PlaylistObservations,
) -> None:
    identifier = str(raw.get("id") or "").strip()
    if identifier:
        facts.ids.add(identifier)
    title = str(raw.get("name") or "").strip()
    if not title:
        return
    names = artist_names(raw)
    title_key = normalize_name(without_sliding_qualifiers(title))
    for credit in names:
        normalized = normalize_name(credit)
        if normalized and title_key:
            facts.keys.add((normalized, title_key))
    if names and normalize_name(names[0]):
        facts.primary.add(normalize_name(names[0]))


def _has_more(page: dict[str, object], offset: int) -> bool:
    total = page.get("total")
    if "next" not in page and isinstance(total, int):
        return offset < total
    return bool(page.get("next"))


def _result(page: dict[str, object], facts: PlaylistObservations) -> PlaylistState:
    total = page.get("total")
    size = total if isinstance(total, int) and "next" not in page else facts.offset
    return PlaylistState(
        size, frozenset(facts.ids), frozenset(facts.keys), frozenset(facts.primary)
    )


def _check_continuation(
    next_page: object, rows: list[object], seen: set[str], playlist: str
) -> None:
    if not rows:
        raise SpotifyTrackResolutionError(
            f"Spotify returned an empty playlist page for {playlist}."
        )
    if not isinstance(next_page, str):
        return
    if next_page in seen:
        raise SpotifyTrackResolutionError(
            f"Spotify repeated a playlist page for {playlist}."
        )
    seen.add(next_page)
