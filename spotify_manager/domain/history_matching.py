"""Historical match qualification and ranking without Spotify or UI dependencies."""

from dataclasses import dataclass
from dataclasses import replace
from difflib import SequenceMatcher

from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.titles import without_sliding_qualifiers


@dataclass(frozen=True)
class SpotifyTrackMatch:
    """One observed track that passed artist and track qualification.

    Args:
        spotify_id: Existing track identity.
        uri: Existing playable track reference.
        track: Observed display title.
        artists: Ordered credited display names.
        album: Observed album name.
        search_rank: One-based original search position.
        track_similarity: Qualified title similarity.
        album_similarity: Album similarity, absent when the export album is missing.
        popularity: Observed popularity, if available.
        liked: Live liked status after qualification.
    """

    spotify_id: str
    uri: str
    track: str
    artists: tuple[str, ...]
    album: str
    search_rank: int
    track_similarity: float
    album_similarity: float | None
    popularity: int | None
    liked: bool = False


@dataclass(frozen=True)
class PlaylistState:
    """Current playlist size and observed membership identities.

    Args:
        total_items: Original observed playlist size.
        track_ids: Observed track identities.
        track_keys: Normalized artist/title pairs for edition-tolerant matching.
        primary_artist_keys: Normalized primary artist identities.
    """

    total_items: int
    track_ids: frozenset[str]
    track_keys: frozenset[tuple[str, str]] = frozenset()
    primary_artist_keys: frozenset[str] = frozenset()


def name_similarity(expected: str, candidate: str) -> float:
    """Compare normalized titles after removing recognized edition qualifiers.

    Args:
        expected: Original Last.fm title.
        candidate: Observed catalog title.

    Returns:
        Sequence similarity, or zero if either normalized title is empty.
    """
    expected_name = normalize_name(without_sliding_qualifiers(expected))
    candidate_name = normalize_name(without_sliding_qualifiers(candidate))
    if not expected_name or not candidate_name:
        return 0.0
    return SequenceMatcher(None, expected_name, candidate_name).ratio()


def qualifying_matches(
    matches: tuple[SpotifyTrackMatch, ...],
    liked_ids: set[str],
    album_threshold: float = 0.9,
) -> tuple[SpotifyTrackMatch, ...]:
    """Apply live liked status, allowing it to override the album threshold.

    Args:
        matches: Artist/track-qualified observations in search order.
        liked_ids: Live liked identities, replacing any stored liked flags.
        album_threshold: Minimum album similarity for unliked matches.

    Returns:
        New observations with current liked status in original order.
    """
    result = []
    for observed in matches:
        match = replace(observed, liked=observed.spotify_id in liked_ids)
        if (
            match.liked
            or match.album_similarity is None
            or match.album_similarity >= album_threshold
        ):
            result.append(match)
    return tuple(result)


def _rank(match: SpotifyTrackMatch) -> tuple[bool, float, float, int, int]:
    return (
        match.liked,
        match.track_similarity,
        match.album_similarity if match.album_similarity is not None else 1.0,
        match.popularity if match.popularity is not None else -1,
        -match.search_rank,
    )


def preferred_match(
    matches: tuple[SpotifyTrackMatch, ...],
    liked_ids: set[str],
    album_threshold: float = 0.9,
) -> SpotifyTrackMatch | None:
    """Rank eligible matches by liked status, similarities, popularity and search rank.

    Args:
        matches: Original observations in search order.
        liked_ids: Live liked identities.
        album_threshold: Overridable album qualification threshold.

    Returns:
        Highest-ranked eligible observation, or none when all matches fail.
    """
    eligible = qualifying_matches(matches, liked_ids, album_threshold)
    if not eligible:
        return None
    return max(eligible, key=_rank)
