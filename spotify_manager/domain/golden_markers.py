"""Pure exact-artist qualification and Golden Oldies marker recipes."""

from collections.abc import Iterable

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.golden_oldies import LastFmTrackStat
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.history_matching import preferred_match


def exact_artists(
    name: str, candidates: tuple[SpotifyArtistCandidate, ...]
) -> tuple[SpotifyArtistCandidate, ...]:
    """Retain normalized exact artist matches without changing search order.

    Args:
        name: Original expected artist spelling.
        candidates: Complete observed candidates.

    Returns:
        Original exact matches, including ambiguous identities.
    """
    expected = normalize_name(name)
    result = []
    for candidate in candidates:
        if normalize_name(candidate.name) == expected:
            result.append(candidate)
    return tuple(result)


def from_match(
    match: SpotifyTrackMatch, source: str, scrobbles: int | None = None
) -> SelectedTrack:
    """Project an original qualified match into a playlist marker.

    Args:
        match: Original selected match.
        source: Original recipe display label.
        scrobbles: Original optional Last.fm play count.

    Returns:
        Original complete marker fields.
    """
    return SelectedTrack(
        match.spotify_id,
        match.uri,
        match.track,
        match.album,
        match.artists,
        source,
        scrobbles,
    )


def lastfm_markers(
    titles: tuple[LastFmTrackStat, ...],
    groups: tuple[tuple[SpotifyTrackMatch, ...], ...],
    liked: set[str],
    album_threshold: float = 0.9,
) -> tuple[SelectedTrack, ...]:
    """Prefer original liked qualified matches and retain first distinct identities.

    Args:
        titles: Original ranked Last.fm titles.
        groups: Complete matches gathered in title order.
        liked: Original live liked identities.
        album_threshold: Original qualification threshold.

    Returns:
        Original usable markers in title order.

    Raises:
        ValueError: Original title and match-group lengths differ.
    """
    result = []
    seen: set[str] = set()
    for title, matches in zip(titles, groups, strict=True):
        match = preferred_match(matches, liked, album_threshold)
        if match is None or match.spotify_id in seen:
            continue
        seen.add(match.spotify_id)
        result.append(from_match(match, "Last.fm top tracks", title.scrobbles))
    return tuple(result)


def distinct_markers(
    tracks: Iterable[SelectedTrack], limit: int
) -> tuple[SelectedTrack, ...]:
    """Retain the original first distinct popular markers up to the configured cap.

    Args:
        tracks: Original complete markers in response order.
        limit: Original selection cap, checked after accepting each marker.

    Returns:
        Original ordered distinct selection.
    """
    result = []
    seen: set[str] = set()
    for track in tracks:
        if track.spotify_id in seen:
            continue
        seen.add(track.spotify_id)
        result.append(track)
        if len(result) == limit:
            break
    return tuple(result)


def album_markers(
    release: DiscographyRelease,
    tracks: tuple[ReleaseTrack, ...],
    artist: SpotifyArtistCandidate,
) -> tuple[SelectedTrack, ...]:
    """Preserve every ordered release track with the original album-source label.

    Args:
        release: Original selected studio release.
        tracks: Original complete release tracklist.
        artist: Original accepted artist mapping.

    Returns:
        Original full selection, without popular-track caps or deduplication.
    """
    result = []
    for track in tracks:
        result.append(
            SelectedTrack(
                track.spotify_id,
                track.uri,
                track.name,
                release.name,
                (artist.name,),
                f"{release.release_type}: {release.name}",
            )
        )
    return tuple(result)
