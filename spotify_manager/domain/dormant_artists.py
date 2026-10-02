"""Rolling dormant-artist eligibility and original liked-track preference."""

from collections import Counter
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import Literal

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name


@dataclass(frozen=True)
class DormantArtist:
    """One artist heard in each prior year and absent from current-year history.

    Args:
        key: Original normalized artist identity.
        name: First observed original display spelling.
        scrobbles: Original eligible prior-year play count.
    """

    key: str
    name: str
    scrobbles: int


@dataclass(frozen=True)
class DormantArtistResult:
    """Original outcome for one alphabetically eligible artist.

    Args:
        artist: Original Last.fm display spelling.
        scrobbles: Original prior-year play count.
        spotify_artist: Original mapped display name, when resolved.
        track: Original preferred marker title, when selected.
        popularity: Original selected marker popularity.
        action: Original added or skipped outcome, including preview added labels.
    """

    artist: str
    scrobbles: int
    spotify_artist: str | None
    track: str | None
    popularity: int | None
    action: Literal["added", "no mapping", "no liked track"]


@dataclass
class _History:
    """Accumulate original first names, prior counts and year membership.

    Args:
        year: Effective current year.
        prior: Original prior-year window.
        heard: Original per-year normalized artist membership.
        current: Current-year exclusions.
        names: First observed display spelling.
        counts: Original prior-year play totals.
    """

    year: int
    prior: set[int]
    heard: dict[int, set[str]]
    current: set[str] = field(default_factory=set)
    names: dict[str, str] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)

    def observe(self, played: date, scrobbles: list[Scrobble]) -> None:
        """Observe one original date group inside the effective year window.

        Args:
            played: Original local history date.
            scrobbles: Original plays in that date group.
        """
        if played.year not in self.prior | {self.year}:
            return
        for scrobble in scrobbles:
            self._remember(scrobble, played.year)

    def _remember(self, scrobble: Scrobble, year: int) -> None:
        key = normalize_name(scrobble.artist)
        if not key:
            return
        self.names.setdefault(key, scrobble.artist)
        if year == self.year:
            self.current.add(key)
            return
        self.heard[year].add(key)
        self.counts[key] += 1


def eligible_artists(
    history: dict[date, list[Scrobble]], year: int, lookback: int = 4
) -> tuple[DormantArtist, ...]:
    """Require each prior year and exclude any current-year listening.

    Args:
        history: Original date-grouped plays in observation order.
        year: Effective current calendar year.
        lookback: Original number of prior years.

    Returns:
        Eligible artists sorted by original display spelling and normalized key.
    """
    prior = set(range(year - lookback, year))
    observed = _History(year, prior, {year: set() for year in prior})
    for played, scrobbles in history.items():
        observed.observe(played, scrobbles)
    eligible = set.intersection(*observed.heard.values()) - observed.current
    artists = []
    for key, count in observed.counts.items():
        if key in eligible:
            artists.append(DormantArtist(key, observed.names[key], count))
    return tuple(sorted(artists, key=_artist_order))


def _artist_order(artist: DormantArtist) -> tuple[str, str]:
    return artist.name.casefold(), artist.key


def most_popular(tracks: tuple[CatalogTrack, ...], top: bool) -> CatalogTrack | None:
    """Retain original descending preference with distinct top/catalog position ties.

    Args:
        tracks: Observed liked tracks in original order.
        top: Apply original top-track rather than catalog tie preference.

    Returns:
        Preferred original observation or no track.
    """
    if not tracks:
        return None
    if top:
        return max(tracks, key=_top_preference)
    return max(tracks, key=_catalog_preference)


def _top_preference(track: CatalogTrack) -> tuple[int, int, str]:
    popularity = track.popularity if track.popularity is not None else -1
    return popularity, -track.track_number, track.name.casefold()


def _catalog_preference(track: CatalogTrack) -> tuple[int, int, int, str]:
    popularity = track.popularity if track.popularity is not None else -1
    return popularity, -track.disc_number, -track.track_number, track.name.casefold()
