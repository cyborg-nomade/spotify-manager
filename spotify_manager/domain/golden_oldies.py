"""Rank exact-label Golden Oldies by their original integer average play date."""

from collections.abc import Iterable
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.domain.history import Scrobble


@dataclass(frozen=True)
class LastFmTrackStat:
    """Original all-time counts for one exact trimmed Last.fm title.

    Args:
        track: Original exact title after trimming surrounding whitespace.
        scrobbles: Original observed play count.
        last_scrobbled_ms: Original latest observed timestamp.
    """

    track: str
    scrobbles: int
    last_scrobbled_ms: int


@dataclass(frozen=True)
class GoldenOldieArtist:
    """Original artist eligible for the oldest-average Golden Oldies ranking.

    Args:
        artist: Exact original artist spelling after surrounding whitespace trim.
        scrobbles: Original observed artist play count.
        average_scrobble_ms: Original integer floor average timestamp.
        first_scrobble_ms: Original earliest play timestamp.
        last_scrobble_ms: Original latest play timestamp.
        top_tracks: Original bounded count-ranked exact titles.
    """

    artist: str
    scrobbles: int
    average_scrobble_ms: int
    first_scrobble_ms: int
    last_scrobble_ms: int
    top_tracks: tuple[LastFmTrackStat, ...]


@dataclass
class _ArtistPlays:
    """Retain original exact-title observations in first-encounter order.

    Args:
        dates: Original artist play timestamps.
        tracks: Original exact-title timestamps in first-title order.
    """

    dates: list[int] = field(default_factory=list)
    tracks: dict[str, list[int]] = field(default_factory=dict)

    def observe(self, track: str, timestamp: int) -> None:
        """Retain one already-trimmed valid-label play.

        Args:
            track: Original exact trimmed title.
            timestamp: Original play timestamp, including negative values.
        """
        self.dates.append(timestamp)
        self.tracks.setdefault(track, []).append(timestamp)

    def artist(self, name: str, limit: int) -> GoldenOldieArtist:
        """Project original timestamps and the bounded title ordering.

        Args:
            name: Original exact trimmed artist name.
            limit: Original configured top-title slice limit.

        Returns:
            Original complete eligible artist facts.
        """
        top: list[LastFmTrackStat] = []
        for track, timestamps in sorted(self.tracks.items(), key=_track_order)[:limit]:
            top.append(LastFmTrackStat(track, len(timestamps), max(timestamps)))
        return GoldenOldieArtist(
            name,
            len(self.dates),
            sum(self.dates) // len(self.dates),
            min(self.dates),
            max(self.dates),
            tuple(top),
        )


def _track_order(item: tuple[str, list[int]]) -> tuple[int, str]:
    return -len(item[1]), item[0].casefold()


def _artist_order(artist: GoldenOldieArtist) -> tuple[int, str]:
    return artist.average_scrobble_ms, artist.artist.casefold()


def _observe(artists: dict[str, _ArtistPlays], play: Scrobble) -> None:
    name, title = play.artist.strip(), play.track.strip()
    if not name or not title:
        return
    artists.setdefault(name, _ArtistPlays()).observe(title, play.timestamp_ms)


def rank_golden_oldies(
    history: Iterable[Scrobble],
    minimum_plays: int = 50,
    top_limit: int = 10,
) -> tuple[GoldenOldieArtist, ...]:
    """Retain original exact-artist counts and oldest-average ordering.

    Args:
        history: Original play observations in source order.
        minimum_plays: Original minimum eligible artist count.
        top_limit: Original top-title slice limit.

    Returns:
        Original eligible artists in integer-average/casefold-name order.
    """
    artists: dict[str, _ArtistPlays] = {}
    for play in history:
        _observe(artists, play)
    ranking: list[GoldenOldieArtist] = []
    for name, plays in artists.items():
        if len(plays.dates) >= minimum_plays:
            ranking.append(plays.artist(name, top_limit))
    return tuple(sorted(ranking, key=_artist_order))
