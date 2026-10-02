"""Count original Berlin annual plays with first labels and stable ties."""

from collections import Counter
from datetime import datetime
from datetime import tzinfo
from typing import NotRequired
from typing import TypedDict

from spotify_manager.domain.history import Scrobble


class YearEntry(TypedDict):
    """Retain original ranked labels and optional resolved marker facts.

    Args:
        artist: Original first untrimmed display artist.
        name: Original first untrimmed title or artist display name.
        scrobbles: Original calendar-year play count.
        uri: Original resolved playable marker, when planning has completed.
        artist_id: Original mapped primary artist, when applicable.
    """

    artist: str
    name: str
    scrobbles: int
    uri: NotRequired[str]
    artist_id: NotRequired[str]


def rank_year(
    history: tuple[Scrobble, ...], year: int, timezone: tzinfo
) -> dict[str, list[YearEntry]]:
    """Count within inclusive Berlin January 1 and exclusive next January 1.

    Args:
        history: Original ordered canonical plays.
        year: Original effective calendar year.
        timezone: Explicit calendar timezone supplied by the outer boundary.

    Returns:
        Original tracks, albums and artists ranked by count and casefolded keys.

    Raises:
        ValueError: The original calendar year cannot form both boundaries.
    """
    start = int(datetime(year, 1, 1, tzinfo=timezone).timestamp() * 1000)
    end = int(datetime(year + 1, 1, 1, tzinfo=timezone).timestamp() * 1000)
    counts: dict[str, Counter[tuple[str, ...]]] = {
        "tracks": Counter(),
        "albums": Counter(),
        "artists": Counter(),
    }
    labels: dict[tuple[str, ...], tuple[str, ...]] = {}
    for play in history:
        if start <= play.timestamp_ms < end:
            _retain_play(play, counts, labels)
    ranked = {}
    for kind, counter in counts.items():
        ranked[kind] = _ranked_entries(kind, counter, labels)
    return ranked


def _retain_play(
    play: Scrobble,
    counts: dict[str, Counter[tuple[str, ...]]],
    labels: dict[tuple[str, ...], tuple[str, ...]],
) -> None:
    parts_by_kind = (
        ("tracks", (play.artist, play.track)),
        ("albums", (play.artist, play.album)),
        ("artists", (play.artist,)),
    )
    for kind, parts in parts_by_kind:
        if not all(part.strip() for part in parts):
            continue
        key = tuple(part.strip().casefold() for part in parts)
        counts[kind][key] += 1
        labels.setdefault((kind, *key), parts)


def _rank_key(item: tuple[tuple[str, ...], int]) -> tuple[int, tuple[str, ...]]:
    return -item[1], item[0]


def _ranked_entries(
    kind: str,
    counter: Counter[tuple[str, ...]],
    labels: dict[tuple[str, ...], tuple[str, ...]],
) -> list[YearEntry]:
    entries: list[YearEntry] = []
    for key, count in sorted(counter.items(), key=_rank_key):
        parts = labels[(kind, *key)]
        entries.append({"artist": parts[0], "name": parts[-1], "scrobbles": count})
    return entries
