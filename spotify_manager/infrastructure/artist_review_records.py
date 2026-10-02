"""Parse original tolerant artist-review Spotify and durable catalog records."""

from typing import Any
from typing import cast

from spotify_manager.application.artist_review_catalog import FirstTrack
from spotify_manager.application.artist_review_catalog import RawReleasePage
from spotify_manager.application.artist_review_catalog import ReleasePage
from spotify_manager.application.artist_review_membership import MembershipPage
from spotify_manager.application.artist_review_membership import QueueMarker
from spotify_manager.domain.artist_review_selection import (
    release_type as classify_release_type,
)
from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate


def artist_ids(raw_item: dict[str, object]) -> tuple[str, ...]:
    """Extract original truthy artist ids in credit order without trimming.

    Args:
        raw_item: Original raw track or release.

    Returns:
        Original ordered credited identities.
    """
    raw_artists = raw_item.get("artists")
    if not isinstance(raw_artists, list):
        return ()
    identities = []
    for artist in raw_artists:
        if isinstance(artist, dict) and artist.get("id"):
            identities.append(str(artist.get("id")))
    return tuple(identities)


def first_artist_name(raw_item: dict[str, object]) -> str:
    """Retain the original first display credit or unknown-artist fallback.

    Args:
        raw_item: Original untrusted track or release.

    Returns:
        Original untrimmed first display name.
    """
    artists = raw_item.get("artists")
    if not isinstance(artists, list) or not artists:
        return "Unknown artist"
    first = artists[0]
    if not isinstance(first, dict):
        return "Unknown artist"
    return str(first.get("name") or "Unknown artist")


def track_candidate(
    raw_track: object, rank: int, target_artist_id: str
) -> TrackCandidate | None:
    """Parse original associated tracks without requiring a primary target credit.

    Args:
        raw_track: Original untrusted Spotify row.
        rank: Original raw search rank.
        target_artist_id: Original expected associated identity.

    Returns:
        Original complete usable track or None.
    """
    if not isinstance(raw_track, dict):
        return None
    identity = _identity(raw_track, target_artist_id)
    if identity is None:
        return None
    return _track(raw_track, rank, identity)


def _identity(
    raw: dict[str, object], artist: str
) -> tuple[tuple[str, ...], str, str] | None:
    ids = artist_ids(raw)
    if artist not in ids or not ids:
        return None
    identity = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    return (ids, identity, uri) if identity and uri else None


def _track(
    raw: dict[str, object], rank: int, identity: tuple[tuple[str, ...], str, str]
) -> TrackCandidate:
    ids, spotify_id, uri = identity
    raw_album = raw.get("album")
    album = (
        str(raw_album.get("name") or "Unknown release")
        if isinstance(raw_album, dict)
        else "Unknown release"
    )
    popularity = raw.get("popularity")
    return TrackCandidate(
        spotify_id,
        str(raw.get("name") or spotify_id),
        uri,
        album,
        rank,
        ids[0],
        first_artist_name(raw),
        ids,
        popularity if isinstance(popularity, int) else None,
    )


def release_type(raw_release: dict[str, object]) -> str:
    """Retain original type casing and four-track single/EP threshold.

    Args:
        raw_release: Original untrusted release.

    Returns:
        Original human-readable release type.
    """
    raw_type = str(raw_release.get("album_type") or "unknown").casefold()
    total = raw_release.get("total_tracks")
    count = total if isinstance(total, int) else 0
    return classify_release_type(raw_type, count)


def release_candidate(
    raw_release: object, rank: int, target_artist_id: str
) -> ReleaseCandidate | None:
    """Parse original associated releases with unchanged integer tolerance.

    Args:
        raw_release: Original untrusted Spotify row.
        rank: Original raw encounter rank.
        target_artist_id: Original expected associated identity.

    Returns:
        Original complete mutable release candidate or None.
    """
    if not isinstance(raw_release, dict):
        return None
    identity = _identity(raw_release, target_artist_id)
    if identity is None:
        return None
    ids, spotify_id, uri = identity
    total = raw_release.get("total_tracks")
    return ReleaseCandidate(
        spotify_id,
        str(raw_release.get("name") or spotify_id),
        uri,
        release_type(raw_release),
        str(raw_release.get("release_date") or "Unknown"),
        total if isinstance(total, int) else 0,
        rank,
        ids[0],
        first_artist_name(raw_release),
        ids,
    )


def cached_tracks(raw: object) -> list[TrackCandidate] | None:
    """Preserve original JSON-constructor behavior, including native field errors.

    Args:
        raw: Original untrusted cached candidate list or another miss value.

    Returns:
        Original reconstructed complete tracks or None for a non-list miss.

    Raises:
        TypeError: The original untrusted constructor fields are invalid.
    """
    if not isinstance(raw, list):
        return None
    tracks = []
    for item in raw:
        # Any is confined to the original permissive JSON constructor boundary.
        tracks.append(TrackCandidate(**cast(dict[str, Any], item)))
    return tracks


def cached_releases(raw: object) -> list[ReleaseCandidate] | None:
    """Preserve original mutable release reconstruction and authoritative empty hits.

    Args:
        raw: Original untrusted cached list or miss value.

    Returns:
        Original reconstructed complete releases or None.

    Raises:
        TypeError: The original untrusted constructor fields are invalid.
    """
    if not isinstance(raw, list):
        return None
    releases = []
    for item in raw:
        # Any is confined to the original permissive JSON constructor boundary.
        releases.append(ReleaseCandidate(**cast(dict[str, Any], item)))
    return releases


def track_page(raw: object, artist: str, name: str) -> list[TrackCandidate]:
    """Parse all original raw rows before applying the caller's ten-track cap.

    Args:
        raw: Original untrusted search response.
        artist: Original expected associated identity.
        name: Original display name for failures.

    Returns:
        Original complete associated candidates in raw rank order.

    Raises:
        ArtistReviewError: The original page or items shape is invalid.
    """
    page = _search_page(raw, "tracks", name)
    tracks = []
    for rank, item in enumerate(cast(list[object], page["items"]), start=1):
        track = track_candidate(item, rank, artist)
        if track is not None:
            tracks.append(track)
    return tracks


def release_page(raw: object, artist: str, name: str, offset: int) -> ReleasePage:
    """Parse original associated release facts with raw-row rank accounting.

    Args:
        raw: Original untrusted search response.
        artist: Original expected associated identity.
        name: Original display name for failures.
        offset: Original raw page offset.

    Returns:
        Original usable candidates and raw pagination authority.

    Raises:
        ArtistReviewError: The original page or items shape is invalid.
    """
    page = _search_page(raw, "albums", name)
    items = cast(list[object], page["items"])
    releases = _releases(items, artist, offset)
    return ReleasePage(tuple(releases), len(items), bool(page.get("next")))


def _search_page(raw: object, kind: str, name: str) -> dict[str, object]:
    label = "track" if kind == "tracks" else "release"
    message = f"Spotify returned invalid {label} search for {name}."
    if not isinstance(raw, dict):
        raise ArtistReviewError(message)
    page = raw.get(kind)
    if not isinstance(page, dict) or not isinstance(page.get("items"), list):
        raise ArtistReviewError(message)
    return page


def scan_page(raw: object, name: str) -> RawReleasePage:
    """Retain complete raw scan rows before delayed candidate parsing.

    Args:
        raw: Original untrusted discography response.
        name: Original reviewed display name.

    Returns:
        Original complete raw rows and next-page truthiness.

    Raises:
        ArtistReviewError: The original raw page or items container is invalid.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ArtistReviewError(f"Spotify returned invalid release data for {name}.")
    return RawReleasePage(tuple(raw["items"]), bool(raw.get("next")))


def scanned_releases(raw: object, artist: str) -> list[ReleaseCandidate]:
    """Qualify original complete scan rows at the original delayed boundary.

    Args:
        raw: Original complete durable scan rows.
        artist: Original expected associated identity.

    Returns:
        Original associated mutable candidates in raw encounter order.

    Raises:
        AssertionError: The original complete scan rows are not a list.
    """
    assert isinstance(raw, list)
    return _releases(raw, artist, 0)


def _releases(items: list[object], artist: str, offset: int) -> list[ReleaseCandidate]:
    releases = []
    for index, raw in enumerate(items, start=1):
        candidate = release_candidate(raw, offset + index, artist)
        if candidate is not None:
            releases.append(candidate)
    return releases


def first_track(raw: object, name: str) -> FirstTrack | None:
    """Parse original first-row marker facts without clearing prior empty results.

    Args:
        raw: Original untrusted first-track response.
        name: Original release display name for failures.

    Returns:
        Original first-row facts or None for empty/non-object first rows.

    Raises:
        ArtistReviewError: The original raw page or items container is invalid.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ArtistReviewError(
            f"Spotify returned invalid first-track data for {name}."
        )
    rows = raw["items"]
    if not rows or not isinstance(rows[0], dict):
        return None
    track = rows[0]
    ids = artist_ids(track)
    return FirstTrack(
        str(track.get("id") or "") or None,
        str(track.get("name") or "") or None,
        str(track.get("uri") or "") or None,
        ids[0] if ids else None,
        first_artist_name(track),
    )


def membership_page(raw: object, identity: str) -> MembershipPage:
    """Parse original current/legacy playlist rows with independent id/credit fields.

    Args:
        raw: Original untrusted complete playlist page.
        identity: Original queue identity for failures.

    Returns:
        Original usable marker facts with complete raw pagination authority.

    Raises:
        ArtistReviewError: Original raw page or items container is invalid.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise ArtistReviewError(
            f"Spotify returned invalid playlist data for {identity}."
        )
    markers = []
    for entry in raw["items"]:
        marker = _queue_marker(entry)
        if marker is not None:
            markers.append(marker)
    total = raw.get("total")
    return MembershipPage(
        tuple(markers),
        len(raw["items"]),
        bool(raw.get("next")),
        total if isinstance(total, int) else None,
    )


def _queue_marker(raw: object) -> QueueMarker | None:
    if not isinstance(raw, dict):
        return None
    track = raw.get("item") or raw.get("track")
    if not isinstance(track, dict):
        return None
    ids = artist_ids(track)
    return QueueMarker(
        str(track.get("id") or "").strip(),
        ids[0] if ids else None,
        str(track.get("uri") or "").strip(),
    )
