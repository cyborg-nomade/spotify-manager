"""Choose original primary markers, tied tracks and release chronology."""

from datetime import date

from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate


def normalize_name(value: str) -> str:
    """Apply the original trimmed, casefolded matching key.

    Args:
        value: Original artist or track display name.

    Returns:
        Original key without accent folding.
    """
    return value.strip().casefold()


def release_date_key(release: ReleaseCandidate) -> tuple[int, int, int, int]:
    """Sort partial Spotify release dates chronologically, unknown dates last.

    Args:
        release: Original complete catalog fact.

    Returns:
        Original validated date key or the unknown-date sentinel.
    """
    if release.release_date == "Unknown":
        return (1, 9999, 12, 31)
    try:
        parts = [int(part) for part in release.release_date.split("-")]
        year = parts[0]
        month = parts[1] if len(parts) > 1 else 1
        day = parts[2] if len(parts) > 2 else 1
        date(year, month, day)
        return (0, year, month, day)
    except ValueError, IndexError:
        return (1, 9999, 12, 31)


def ambiguous_track_choices(candidates: list[TrackCandidate]) -> list[TrackCandidate]:
    """Retain the original popularity-tie priority and first-name fallback.

    Args:
        candidates: Original ordered primary, unliked candidates.

    Returns:
        Original tied choices, duplicate first names or the single first track.
    """
    if not candidates:
        return []
    tied = _popularity_ties(candidates)
    if len(tied) > 1:
        return tied
    top_name = normalize_name(candidates[0].name)
    same_name = []
    for candidate in candidates:
        if normalize_name(candidate.name) == top_name:
            same_name.append(candidate)
    return same_name if len(same_name) > 1 else [candidates[0]]


def _popularity_ties(candidates: list[TrackCandidate]) -> list[TrackCandidate]:
    if not all(candidate.popularity is not None for candidate in candidates):
        return []
    top_popularity = max(candidate.popularity or 0 for candidate in candidates)
    tied = []
    for candidate in candidates:
        if candidate.popularity == top_popularity:
            tied.append(candidate)
    return tied


def queue_check_order(
    playlists: tuple[str, str, str], liked_count: int
) -> tuple[str, str, str]:
    """Return original placement precedence while retaining sticky existing tiers.

    Args:
        playlists: Original queue-one, queue-two and queue-three identities.
        liked_count: Original local liked count.

    Returns:
        Original lookup order; high counts still start in queue two.
    """
    one, two, three = playlists
    return playlists if liked_count <= 5 else (two, three, one)


def earliest_releases(candidates: list[ReleaseCandidate]) -> list[ReleaseCandidate]:
    """Retain the last duplicate record, sort by original date and rerank ten releases.

    Args:
        candidates: Complete qualified original raw scan in encounter order.

    Returns:
        Original ten earliest distinct mutable release records.
    """
    by_id = {}
    for candidate in candidates:
        by_id[candidate.spotify_id] = candidate
    releases = sorted(by_id.values(), key=release_date_key)[:10]
    for rank, release in enumerate(releases, start=1):
        release.rank = rank
    return releases


def log_int(value: object) -> int:
    """Retain original pending-decision integer tolerance without normalizing plans.

    Args:
        value: Original optional audit count.

    Returns:
        Original integer conversion or zero after an invalid numeric string.
    """
    try:
        return int(str(value))
    except ValueError:
        return 0


def spotify_search_query(artist_name: str) -> str:
    """Retain original quoted artist-filter syntax and quote replacement.

    Args:
        artist_name: Original display artist name.

    Returns:
        Original exact-ish Spotify search filter.
    """
    clean_name = artist_name.replace('"', " ").strip()
    return f'artist:"{clean_name}"'


def release_type(raw_type: str, track_count: int) -> str:
    """Retain original release type labels and the inclusive four-track EP rule.

    Args:
        raw_type: Original untrimmed casefolded Spotify type.
        track_count: Original integer track count, including booleans and negatives.

    Returns:
        Original album/compilation/EP/single label or title-cased unknown type.
    """
    if raw_type == "album":
        return "Album"
    if raw_type == "compilation":
        return "Compilation"
    if raw_type == "ep":
        return "EP"
    if raw_type == "single":
        return "EP" if track_count >= 4 else "Single"
    return raw_type.title() or "Unknown"
