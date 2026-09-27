"""Artist-completion reasons and marker selection over observed catalog facts."""

from spotify_manager.domain.artists import ArtistFacts
from spotify_manager.domain.artists import promotion_reasons
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.releases import review_date_key


def qualification_reasons(
    catalog: tuple[RankedRelease, ...],
    saved: dict[str, bool],
    *,
    liked_tracks: int,
    total_tracks: int,
) -> tuple[str, ...]:
    """Translate catalog facts into the existing ordered promotion messages.

    Args:
        catalog: Observed catalog entries, retaining duplicate albums.
        saved: All observed saved statuses, including extra response entries.
        liked_tracks: Unique liked primary-artist count.
        total_tracks: Unique primary-artist catalog count.

    Returns:
        Every matching promotion message in its original order.
    """
    album_statuses = []
    for release in catalog:
        if release.release_type == "Album":
            album_statuses.append(saved.get(release.spotify_id, False))
    facts = ArtistFacts(
        liked_tracks, total_tracks, sum(saved.values()), tuple(album_statuses)
    )
    return tuple(reason.value for reason in promotion_reasons(facts))


def representative_track(
    artist_id: str,
    catalog: tuple[RankedRelease, ...],
    tracks: dict[str, tuple[CatalogTrack, ...]],
) -> CatalogTrack | None:
    """Select the first primary-credit track in preferred chronological order.

    Args:
        artist_id: Artist whose marker is required.
        catalog: Parsed review catalog, including fallback tiers.
        tracks: Previously observed ordered release tracks.

    Returns:
        Earliest preferred marker, or None when no primary credit exists.
    """
    for release in sorted(catalog, key=_chronology):
        track = _first_primary(tracks.get(release.spotify_id, ()), artist_id)
        if track is not None:
            return track
    return None


def _chronology(release: RankedRelease) -> tuple[bool, tuple[int, int, int, str], str]:
    return (
        release.tier != 0,
        review_date_key(release.release_date),
        release.name.casefold(),
    )


def _first_primary(
    tracks: tuple[CatalogTrack, ...], artist_id: str
) -> CatalogTrack | None:
    for track in tracks:
        if track.primary_artist_id == artist_id:
            return track
    return None


def first_liked(
    tracks: tuple[CatalogTrack, ...], liked: dict[str, bool]
) -> CatalogTrack | None:
    """Retain the first liked track in the original top-track response order.

    Args:
        tracks: Observed top-track sequence.
        liked: Live liked statuses, treating absent IDs as unliked.

    Returns:
        First liked marker, or None.
    """
    for track in tracks:
        if liked.get(track.spotify_id, False):
            return track
    return None


def popular_liked_track(
    tracks: list[CatalogTrack], popularities: dict[str, int]
) -> CatalogTrack | None:
    """Select the original popularity fallback with descending casefolded-title ties.

    Args:
        tracks: Unique liked primary-artist catalog tracks in encounter order.
        popularities: Live popularity observations; missing IDs rank at minus one.

    Returns:
        Highest-ranked marker, retaining first encounter for exact ties, or None.
    """
    selected = None
    best: tuple[int, str] | None = None
    for track in tracks:
        rank = popularities.get(track.spotify_id, -1), track.name.casefold()
        if best is None or rank > best:
            selected, best = track, rank
    return selected
