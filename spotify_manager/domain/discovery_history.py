"""Current-year listening evidence for New Kids and Queue 2 release completion."""

from collections.abc import Mapping
from collections.abc import Sequence
from datetime import date

from spotify_manager.domain.completion import release_completed
from spotify_manager.domain.completion import scrobble_threshold
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.releases import release_identity
from spotify_manager.domain.titles import without_sliding_qualifiers


type AnnualReleaseKey = tuple[str, str]
type AnnualScrobbleIndex = dict[AnnualReleaseKey, frozenset[str]]


def annual_release_key(artist: str, release: str) -> AnnualReleaseKey:
    """Retain the existing artist and edition-neutral release identity pair.

    Args:
        artist: Original credited artist name.
        release: Original release title.

    Returns:
        Artist identity without spaces and release identity retaining word boundaries.
    """
    return normalize_name(artist), release_identity(release)


def scrobble_track_identity(name: str) -> str:
    """Normalize track titles with the original two-stage edition codec.

    Args:
        name: Last.fm or Spotify track title.

    Returns:
        Edition-neutral track identity, retaining normalized word boundaries.
    """
    return release_identity(without_sliding_qualifiers(name))


def annual_scrobble_index(
    history: Mapping[date, Sequence[Scrobble]], year: int
) -> AnnualScrobbleIndex:
    """Index distinct normalized titles within the supplied local calendar year.

    Args:
        history: Listening events already grouped by their original Berlin-local dates.
        year: Active invocation year.

    Returns:
        Distinct nonempty normalized titles grouped by nonempty artist/release keys.
    """
    indexed: dict[AnnualReleaseKey, set[str]] = {}
    for day, scrobbles in history.items():
        if day.year == year:
            _index_scrobbles(indexed, scrobbles)
    return _freeze_index(indexed)


def _index_scrobbles(
    indexed: dict[AnnualReleaseKey, set[str]], scrobbles: Sequence[Scrobble]
) -> None:
    for scrobble in scrobbles:
        key = annual_release_key(scrobble.artist, scrobble.album)
        title = scrobble_track_identity(scrobble.track)
        if all(key) and title:
            indexed.setdefault(key, set()).add(title)


def _freeze_index(indexed: dict[AnnualReleaseKey, set[str]]) -> AnnualScrobbleIndex:
    result = {}
    for key, titles in indexed.items():
        result[key] = frozenset(titles)
    return result


def review_catalog(
    catalog: tuple[RankedRelease, ...], release_limit: int = 4
) -> tuple[RankedRelease, ...]:
    """Use fallback releases only when too few preferred studio entries exist.

    Args:
        catalog: Original ordered catalog, retaining duplicate entries.
        release_limit: Existing required studio count.

    Returns:
        Preferred studio sequence when sufficient, otherwise the complete catalog.
    """
    preferred = tuple(release for release in catalog if release.tier == 0)
    return preferred if len(preferred) >= release_limit else catalog


def scrobbled_titles(index: AnnualScrobbleIndex, release_identity: str) -> set[str]:
    """Collect the original inexpensive title prefilter across every credited artist.

    Args:
        index: Current-year normalized evidence.
        release_identity: Catalog release identity used before observing track credits.

    Returns:
        Distinct titles under matching release keys, regardless of artist identity.
    """
    titles: set[str] = set()
    for (_artist, album), names in index.items():
        if album == release_identity:
            titles.update(names)
    return titles


def release_was_played(
    release: RankedRelease,
    tracks: tuple[CatalogTrack, ...],
    liked: dict[str, bool],
    index: AnnualScrobbleIndex,
    studio_minimum: int = 3,
) -> bool:
    """Require enough distinct played titles plus every liked title across credits.

    Args:
        release: Catalog release under review.
        tracks: Original ordered tracks with individual primary credits.
        liked: Live memberships; missing entries remain unliked.
        index: Current-year normalized listening evidence.
        studio_minimum: Existing distinct-title threshold for studio releases.

    Returns:
        Whether both the tier minimum and liked-title completeness rules hold.
    """
    matched: set[str] = set()
    liked_names: set[str] = set()
    for track in tracks:
        name = scrobble_track_identity(track.name)
        key = annual_release_key(track.primary_artist_name, release.name)
        if name in index.get(key, frozenset()):
            matched.add(name)
        if liked.get(track.spotify_id, False):
            liked_names.add(name)
    return release_completed(
        matched, liked_names, scrobble_threshold(release.tier, studio_minimum)
    )
