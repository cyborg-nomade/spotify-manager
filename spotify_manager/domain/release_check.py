"""Original release eligibility, partial-date windows and playlist identity policies."""

import calendar
import re
from collections import Counter
from collections import defaultdict
from datetime import date
from functools import partial

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.release_check_values import NEW_VINTAGE_ARTIST_LIMIT
from spotify_manager.domain.release_check_values import PlaylistEntry
from spotify_manager.domain.release_check_values import PlaylistMembership
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack
from spotify_manager.domain.titles import without_sliding_qualifiers


EP_MARKER = re.compile(r"(?:^|[\s\-[(])e\.?p\.?(?:$|[\s\-)\]])", re.IGNORECASE)
ALWAYS_EXCLUDED_RELEASE = re.compile(
    r"\b(?:anthology|best of|collection|compilation|greatest hits|rarities|"
    r"cast recording|motion picture|original score|soundtrack|bootleg|demos?|"
    r"karaoke|remix(?:es)?)\b",
    re.IGNORECASE,
)
LIVE_RELEASE = re.compile(
    r"(?:^live(?:!|$|\s+(?:at|from|in|on)\b)|"
    r"[\[(][^)\]]*\blive\b[^)\]]*[)\]]|"
    r"\s[-\N{EN DASH}\N{EM DASH}]\s.*\blive\b.*$|"
    r"\b(?:ao vivo|en vivo|in concert|unplugged)\b)",
    re.IGNORECASE,
)
EDITION_RELEASE = re.compile(
    r"\b(?:anniversary|bonus|collector(?:'s)?|deluxe|edition|expanded|legacy|"
    r"mono|remaster(?:ed)?|reissue|special|stereo|super deluxe)\b",
    re.IGNORECASE,
)
DELUXE_RELEASE = re.compile(r"\b(?:deluxe|super deluxe)\b", re.IGNORECASE)


def release_date_interval(release: ReleaseCandidate) -> tuple[date, date] | None:
    """Resolve the original possible calendar interval for Spotify date precision.

    Args:
        release: Original precision-preserving observed release.

    Returns:
        Inclusive original date interval, or no valid date.
    """
    try:
        parts = [int(part) for part in release.release_date.split("-")]
        year = parts[0]
        precision = release.release_date_precision.casefold()
        if precision == "year" or len(parts) == 1:
            return date(year, 1, 1), date(year, 12, 31)
        month = parts[1]
        if precision == "month" or len(parts) == 2:
            return (
                date(year, month, 1),
                date(year, month, calendar.monthrange(year, month)[1]),
            )
        day = parts[2]
        parsed = date(year, month, day)
        return parsed, parsed
    except IndexError, ValueError:
        return None


def release_scope_reason(
    release: ReleaseCandidate,
    artist_rank: int,
    vintage_limit: int = NEW_VINTAGE_ARTIST_LIMIT,
) -> str | None:
    """Apply original title and artist-rank rules to albums and EPs.

    Args:
        release: Original observed release.
        artist_rank: Original global Last.fm artist rank.
        vintage_limit: Original top-artist boundary for live/deluxe eligibility.

    Returns:
        Original exclusion reason, or eligibility.
    """
    if release.release_type not in {"Album", "EP"}:
        return f"{release.release_type.casefold()} is not an album or EP"
    if ALWAYS_EXCLUDED_RELEASE.search(release.name):
        return "compilation or other non-release-project title"
    if artist_rank <= vintage_limit:
        if EDITION_RELEASE.search(release.name) and not DELUXE_RELEASE.search(
            release.name
        ):
            return "non-deluxe reissue or remaster"
        return None
    if LIVE_RELEASE.search(release.name):
        return "live release outside the top 50"
    if EDITION_RELEASE.search(release.name):
        return "deluxe edition, reissue, or remaster outside the top 50"
    return None


def release_type(raw_type: object, total_tracks: int, name: str) -> str:
    """Infer the original release kind from raw Spotify metadata and EP markers.

    Args:
        raw_type: Original untrusted release-kind metadata.
        total_tracks: Original observed track count.
        name: Original display title.

    Returns:
        Original display kind, including title-cased unknown values.
    """
    normalized = str(raw_type or "").casefold()
    if normalized == "album":
        return "Album"
    if normalized == "single" and (total_tracks >= 4 or EP_MARKER.search(name)):
        return "EP"
    if normalized == "single":
        return "Single"
    if normalized == "ep":
        return "EP"
    if normalized == "compilation":
        return "Compilation"
    return normalized.title() or "Unknown"


def release_tags(release: ReleaseCandidate) -> tuple[str, ...]:
    """Preserve original live-before-deluxe review labels.

    Args:
        release: Original observed display title.

    Returns:
        Original ordered special-release labels.
    """
    tags: list[str] = []
    if LIVE_RELEASE.search(release.name):
        tags.append("LIVE")
    if DELUXE_RELEASE.search(release.name):
        tags.append("DELUXE")
    return tuple(tags)


def released_during(
    release: ReleaseCandidate,
    checked_from: date,
    checked_through: date,
) -> bool:
    """Check original inclusive partial-date overlap with the run window.

    Args:
        release: Original observed release.
        checked_from: Inclusive original start date.
        checked_through: Inclusive original end date.

    Returns:
        Whether the original date interval overlaps the window.
    """
    interval = release_date_interval(release)
    return bool(
        interval and interval[0] <= checked_through and interval[1] >= checked_from
    )


def future_record(
    release: ReleaseCandidate,
    checked_through: date,
    artist_rank: int,
) -> bool:
    """Identify a definitely unreleased eligible original album or EP.

    Args:
        release: Original observed release.
        checked_through: Inclusive original run end date.
        artist_rank: Original global artist rank.

    Returns:
        Whether its earliest possible date is after the run window and it is eligible.
    """
    interval = release_date_interval(release)
    return bool(
        interval
        and interval[0] > checked_through
        and release_scope_reason(release, artist_rank) is None
    )


def release_identity(release: ReleaseCandidate) -> tuple[str, str, str]:
    """Preserve original market-duplicate identity without collapsing edition titles.

    Args:
        release: Original observed release.

    Returns:
        Normalized full title, original date and original kind.
    """
    return (
        normalize_name(release.name),
        release.release_date,
        release.release_type,
    )


def membership(entries: tuple[PlaylistEntry, ...]) -> PlaylistMembership:
    """Index original playlist items by identities and conservative title keys.

    Args:
        entries: Original ordered playable items.

    Returns:
        Mutable original membership indexes.
    """
    track_ids = {entry.spotify_id for entry in entries if entry.spotify_id}
    track_keys: set[tuple[str, str]] = set()
    primary_artist_ids: set[str] = set()
    for entry in entries:
        if entry.primary_artist_id:
            primary_artist_ids.add(entry.primary_artist_id)
        artist_key = normalize_name(entry.primary_artist_name or "")
        track_key = normalize_name(without_sliding_qualifiers(entry.name))
        if artist_key and track_key:
            track_keys.add((artist_key, track_key))
    return PlaylistMembership(
        track_ids=track_ids,
        track_keys=track_keys,
        primary_artist_ids=primary_artist_ids,
    )


def deduplicated_entries(
    entries: tuple[PlaylistEntry, ...],
) -> tuple[PlaylistEntry, ...]:
    """Retain the first Wine Cellar marker per known primary Spotify artist.

    Args:
        entries: Original ordered playable items.

    Returns:
        Retained original order, preserving all unknown primary credits.
    """
    seen_artist_ids: set[str] = set()
    kept: list[PlaylistEntry] = []
    for entry in entries:
        artist_id = entry.primary_artist_id
        if artist_id and artist_id in seen_artist_ids:
            continue
        kept.append(entry)
        if artist_id:
            seen_artist_ids.add(artist_id)
    return tuple(kept)


def track_key(track: ReleaseTrack) -> tuple[str, str]:
    """Normalize original primary credit and qualifier-tolerant track title.

    Args:
        track: Original observed release track.

    Returns:
        Original normalized artist and title identity.
    """
    return (
        normalize_name(track.primary_artist_name),
        normalize_name(without_sliding_qualifiers(track.name)),
    )


def track_is_present(
    membership: PlaylistMembership,
    track: ReleaseTrack,
) -> bool:
    """Check original exact-ID or normalized artist/title membership.

    Args:
        membership: Original mutable membership.
        track: Original selected marker.

    Returns:
        Whether either original track identity is represented.
    """
    return (
        track.spotify_id in membership.track_ids
        or track_key(track) in membership.track_keys
    )


def artist_is_present(
    membership: PlaylistMembership,
    spotify_artist: SpotifyArtistCandidate,
) -> bool:
    """Check original first-credit artist membership.

    Args:
        membership: Original mutable membership.
        spotify_artist: Original resolved artist mapping.

    Returns:
        Whether the original mapped artist identity is represented.
    """
    return spotify_artist.spotify_id in membership.primary_artist_ids


def rank_artists(
    history: tuple[Scrobble, ...], minimum: int = 100
) -> tuple[RankedArtist, ...]:
    """Rank original normalized plays before applying the minimum eligibility boundary.

    Args:
        history: Original ordered canonical plays.
        minimum: Original minimum artist play count.

    Returns:
        Ranked artists with majority display spelling and deterministic ties.
    """
    counts: Counter[str] = Counter()
    names: dict[str, Counter[str]] = defaultdict(Counter)
    for scrobble in history:
        name = scrobble.artist.strip()
        key = normalize_name(name)
        if not key:
            continue
        counts[key] += 1
        names[key][name] += 1
    ordered = sorted(counts, key=partial(_artist_rank, counts))
    ranking = []
    for rank, key in enumerate(ordered, start=1):
        if counts[key] < minimum:
            continue
        display_name = min(names[key], key=partial(_display_rank, names[key]))
        ranking.append(RankedArtist(key, display_name, counts[key], rank))
    return tuple(ranking)


def _artist_rank(counts: Counter[str], key: str) -> tuple[int, str]:
    return -counts[key], key


def _display_rank(names: Counter[str], name: str) -> tuple[int, str, str]:
    return -names[name], name.casefold(), name
