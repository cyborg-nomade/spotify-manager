"""Decode release-check identities with original metadata tolerance."""

from collections.abc import Callable

from spotify_manager.application.release_check_values import ReleaseCheckSpotifyError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.release_check import release_type
from spotify_manager.domain.release_check_values import ReleaseCandidate
from spotify_manager.domain.release_check_values import ReleaseTrack


def positive_int(raw: object) -> int | None:
    """Retain original nonnegative integer metadata while excluding booleans.

    Args:
        raw: Original untrusted metadata.

    Returns:
        Original valid integer or no valid value.
    """
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    return None


def artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Retain original credit order, ID fallback and blank-name tolerance.

    Args:
        raw: Original untrusted artist-credit metadata.

    Returns:
        Original ordered nonblank identities and coerced display names.
    """
    if not isinstance(raw, list):
        return ()
    artists: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        spotify_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or spotify_id).strip()
        if spotify_id:
            artists.append((spotify_id, name))
    return tuple(artists)


def parse_artist(
    raw: object,
    rank: int,
    expected_name: str,
) -> SpotifyArtistCandidate | None:
    """Decode one original complete artist mapping observation.

    Args:
        raw: Original untrusted artist row.
        rank: Original unfiltered search position.
        expected_name: Original Last.fm display spelling.

    Returns:
        Original complete mapping or no usable observation.
    """
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    if not spotify_id or not name or not uri:
        return None
    raw_followers = raw.get("followers")
    followers = (
        positive_int(raw_followers.get("total"))
        if isinstance(raw_followers, dict)
        else None
    )
    return SpotifyArtistCandidate(
        spotify_id=spotify_id,
        name=name,
        uri=uri,
        popularity=positive_int(raw.get("popularity")),
        followers=followers,
        search_rank=rank,
        exact_name=(normalize_name(name) == normalize_name(expected_name)),
    )


def parse_release(
    raw: object,
    artist_id: str,
) -> ReleaseCandidate | None:
    """Decode an original complete release with the exact first credited identity.

    Args:
        raw: Original untrusted release row.
        artist_id: Original mapped primary artist identity.

    Returns:
        Original release metadata or no eligible observation.
    """
    if not isinstance(raw, dict):
        return None
    artists = artist_pairs(raw.get("artists"))
    if not artists or artists[0][0] != artist_id:
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    release_date = str(raw.get("release_date") or "").strip()
    if not spotify_id or not uri or not name or not release_date:
        return None
    total_tracks = positive_int(raw.get("total_tracks")) or 0
    return ReleaseCandidate(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        release_type=release_type(raw.get("album_type"), total_tracks, name),
        release_date=release_date,
        release_date_precision=str(raw.get("release_date_precision") or "day"),
        total_tracks=total_tracks,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
    )


def parse_track(raw: object, fallback_position: int) -> ReleaseTrack | None:
    """Decode an original playable track with original position fallback.

    Args:
        raw: Original untrusted track row.
        fallback_position: Original playable-count-based fallback.

    Returns:
        Original complete marker or no usable observation.
    """
    if not isinstance(raw, dict):
        return None
    spotify_id = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    artists = artist_pairs(raw.get("artists"))
    if not spotify_id or not uri or not name or not artists:
        return None
    disc_number = positive_int(raw.get("disc_number")) or 1
    track_number = positive_int(raw.get("track_number")) or fallback_position
    return ReleaseTrack(
        spotify_id=spotify_id,
        uri=uri,
        name=name,
        primary_artist_id=artists[0][0],
        primary_artist_name=artists[0][1],
        disc_number=disc_number,
        track_number=track_number,
    )


def parse_artist_search(
    response: object,
    expected_name: str,
    parser: Callable[[object, int, str], SpotifyArtistCandidate | None],
) -> tuple[SpotifyArtistCandidate, ...]:
    """Decode original artist-search rows without deduplication or reordering.

    Args:
        response: Original untrusted SDK response.
        expected_name: Original Last.fm artist display spelling.
        parser: Original compatibility observation seam for each row.

    Returns:
        Original complete observations in search order with original ranks.

    Raises:
        ReleaseCheckSpotifyError: The original response lacks its items list.
    """
    page = response.get("artists") if isinstance(response, dict) else None
    items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(items, list):
        raise ReleaseCheckSpotifyError(
            f"Spotify returned invalid artist search data for {expected_name}."
        )
    observed = []
    for rank, row in enumerate(items, start=1):
        candidate = parser(row, rank, expected_name)
        if candidate is not None:
            observed.append(candidate)
    return tuple(observed)
