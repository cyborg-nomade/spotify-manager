"""Sauvignon album identity, edition preference and track-evidence ranking rules."""

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import date

from spotify_manager.domain.discovery_progression import DECORATED_PATTERN
from spotify_manager.domain.discovery_progression import release_kind
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from spotify_manager.domain.recommendation_history import weekly_weighted_rank
from spotify_manager.domain.releases import release_identity


AlbumKey = tuple[str, str]


@dataclass(frozen=True)
class SpotifyAlbumOption:
    """One eligible observed album edition reached through a recommended track.

    Args:
        spotify_id: Original album identity.
        uri: Original album reference.
        artist_id: Original primary credited album artist identity.
        artist: Original primary credited album artist name.
        album: Original album display title.
        release_type: Original eligible release type.
        release_date: Original catalog release-date text.
        total_tracks: Original catalog track count.
        source_track: Original matched track display title.
        source_track_id: Original matched track identity.
        search_rank: Original one-based search position.
        track_similarity: Original qualified title similarity.
        track_popularity: Original observed popularity, if present.
    """

    spotify_id: str
    uri: str
    artist_id: str
    artist: str
    album: str
    release_type: str
    release_date: str
    total_tracks: int
    source_track: str
    source_track_id: str
    search_rank: int
    track_similarity: float
    track_popularity: int | None


@dataclass(frozen=True)
class FirstTrack:
    """First observed playable track in a chosen album's original stored order.

    Args:
        spotify_id: Original playable track identity.
        uri: Original playable track reference.
        name: Original stripped display title.
    """

    spotify_id: str
    uri: str
    name: str


@dataclass(frozen=True)
class AlbumRecommendation:
    """Album-level support accumulated from original recommended tracks.

    Args:
        artist: First observed group's strongest edition artist spelling.
        album: First observed group's strongest edition title spelling.
        key: Original edition-tolerant artist and album identity.
        score: Weighted title support with the original distinct-track bonus.
        best_match: Highest original neighborhood score, starting at zero.
        supporting_tracks: Sorted distinct original candidate display labels.
        options: Preferred observed editions in original deterministic order.
        base_rank: One-based original support rank.
        weekly_rank: Original deterministic weighted weekly score.
    """

    artist: str
    album: str
    key: AlbumKey
    score: float
    best_match: float
    supporting_tracks: tuple[str, ...]
    options: tuple[SpotifyAlbumOption, ...]
    base_rank: int = 0
    weekly_rank: float = 1.0


@dataclass
class _AlbumAccumulator:
    """Mutable album evidence before original support and weekly ranking.

    Args:
        artist: First strongest observed edition's display artist.
        album: First strongest observed edition's display album.
        key: Original normalized album identity.
        score: Accumulated track-weighted title support.
        best_match: Highest observed neighborhood score, starting at zero.
        supporting_tracks: Original distinct display labels, initialized when absent.
        options: Preferred observations per album identity, initialized when absent.
    """

    artist: str
    album: str
    key: AlbumKey
    score: float = 0.0
    best_match: float = 0.0
    supporting_tracks: set[str] | None = None
    options: dict[str, SpotifyAlbumOption] | None = None

    def __post_init__(self) -> None:
        """Initialize absent storage while retaining supplied support and editions."""
        if self.supporting_tracks is None:
            self.supporting_tracks = set()
        if self.options is None:
            self.options = {}


def canonical_album_key(artist: str, album: str) -> AlbumKey:
    """Build the original edition-tolerant artist and album identity.

    Args:
        artist: Original credited artist spelling.
        album: Original album display title.

    Returns:
        Normalized artist and edition-neutral release title.
    """
    return normalize_name(artist), release_identity(album)


def heard_album_keys(scrobbles: list[Scrobble]) -> set[AlbumKey]:
    """Retain every original nonempty album identity present in canonical history.

    Args:
        scrobbles: Original ordered canonical plays.

    Returns:
        Distinct valid album identities, excluding absent album names.
    """
    keys = set()
    for scrobble in scrobbles:
        if not scrobble.album:
            continue
        key = canonical_album_key(scrobble.artist, scrobble.album)
        if all(key):
            keys.add(key)
    return keys


def option_rank(option: SpotifyAlbumOption) -> tuple[float, int, int]:
    """Rank an edition by original title similarity, popularity and search position.

    Args:
        option: Original eligible observed edition.

    Returns:
        Original preference components, with missing popularity ranked below zero.
    """
    return (
        option.track_similarity,
        option.track_popularity if option.track_popularity is not None else -1,
        -option.search_rank,
    )


def option_sort_key(option: SpotifyAlbumOption) -> tuple[float, int, int, str]:
    """Order preferred editions with the original identity tie-breaker.

    Args:
        option: Original eligible observed edition.

    Returns:
        Descending preference components followed by ascending album identity.
    """
    rank = option_rank(option)
    return -rank[0], -rank[1], -rank[2], option.spotify_id


def genuinely_ambiguous(options: tuple[SpotifyAlbumOption, ...]) -> bool:
    """Compare original visible metadata before requesting an edition choice.

    Args:
        options: Original preferred edition observations.

    Returns:
        Whether normalized title, literal date, track count or release type differs.
    """
    signatures = set()
    for option in options:
        signatures.add(
            (
                normalize_name(option.album),
                option.release_date,
                option.total_tracks,
                option.release_type,
            )
        )
    return len(signatures) > 1


def _groups(
    options: tuple[SpotifyAlbumOption, ...],
    excluded: set[AlbumKey],
    existing: set[str],
) -> dict[AlbumKey, list[SpotifyAlbumOption]]:
    grouped: dict[AlbumKey, list[SpotifyAlbumOption]] = {}
    for option in options:
        key = canonical_album_key(option.artist, option.album)
        if key in excluded or option.spotify_id in existing:
            continue
        grouped.setdefault(key, []).append(option)
    return grouped


def _remember(
    options: dict[str, SpotifyAlbumOption], group: list[SpotifyAlbumOption]
) -> None:
    for option in group:
        previous = options.get(option.spotify_id)
        if previous is None or option_rank(option) > option_rank(previous):
            options[option.spotify_id] = option


def _recommendation(value: _AlbumAccumulator) -> AlbumRecommendation:
    return AlbumRecommendation(
        value.artist,
        value.album,
        value.key,
        value.score * (1 + 0.15 * (len(value.supporting_tracks or ()) - 1)),
        value.best_match,
        tuple(sorted(value.supporting_tracks or ())),
        tuple(sorted((value.options or {}).values(), key=option_sort_key)),
    )


def _base_rank(item: AlbumRecommendation) -> tuple[float, int, float, AlbumKey]:
    return -item.score, -len(item.supporting_tracks), -item.best_match, item.key


def _weekly_rank(item: AlbumRecommendation) -> tuple[float, int, AlbumKey]:
    return -item.weekly_rank, item.base_rank, item.key


@dataclass
class AlbumEvidence:
    """Combine each track once per album identity and preserve preferred editions.

    Args:
        excluded: Original heard and previously added album identities.
        existing: Original represented destination album identities.
        accumulators: Original first-encountered mutable album evidence.
    """

    excluded: set[AlbumKey]
    existing: set[str]
    accumulators: dict[AlbumKey, _AlbumAccumulator] = field(default_factory=dict)

    def observe(
        self, candidate: FoundArtCandidate, options: tuple[SpotifyAlbumOption, ...]
    ) -> None:
        """Combine one original candidate's eligible album observations.

        Args:
            candidate: Original ranked recommended track.
            options: Ordered eligible album observations from its search.

        Raises:
            AssertionError: Initialized support or edition storage is corrupted.
        """
        for key, group in _groups(options, self.excluded, self.existing).items():
            self._observe_group(candidate, key, group)

    def _observe_group(
        self,
        candidate: FoundArtCandidate,
        key: AlbumKey,
        group: list[SpotifyAlbumOption],
    ) -> None:
        best = max(group, key=option_rank)
        accumulator = self.accumulators.setdefault(
            key, _AlbumAccumulator(best.artist, best.album, key)
        )
        accumulator.score += candidate.score * best.track_similarity
        accumulator.best_match = max(accumulator.best_match, candidate.best_match)
        assert accumulator.supporting_tracks is not None
        assert accumulator.options is not None
        accumulator.supporting_tracks.add(f"{candidate.artist} - {candidate.track}")
        _remember(accumulator.options, group)

    def ranked(self, week: date) -> tuple[AlbumRecommendation, ...]:
        """Apply original distinct-track support bonuses and weekly album rotation.

        Args:
            week: Original effective listening week.

        Returns:
            Ranked recommendations with original support and preferred editions.
        """
        base = sorted(
            (_recommendation(value) for value in self.accumulators.values()),
            key=_base_rank,
        )
        rotated = []
        for rank, recommendation in enumerate(base, start=1):
            rotated.append(
                replace(
                    recommendation,
                    base_rank=rank,
                    weekly_rank=weekly_weighted_rank(
                        week,
                        "sauvignon-album",
                        recommendation.key,
                        recommendation.score**2,
                    ),
                )
            )
        return tuple(sorted(rotated, key=_weekly_rank))


def eligible_release_type(raw_type: object, total_tracks: int, name: str) -> str | None:
    """Retain original plain studio albums and EPs after release classification.

    Args:
        raw_type: Original raw catalog release classification.
        total_tracks: Original coerced track count.
        name: Original stripped display title.

    Returns:
        Original eligible classification or none for other/decorated releases.
    """
    kind, tier = release_kind(raw_type, total_tracks, name)
    if tier != 0 or DECORATED_PATTERN.search(name):
        return None
    return kind
