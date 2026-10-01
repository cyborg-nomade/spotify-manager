"""Tolerant original Spotify album-evidence and first-track response codecs."""

from collections.abc import Callable

from spotify_manager.application.sauvignon_values import SauvignonSpotifyError
from spotify_manager.domain.album_recommendations import FirstTrack
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_recommendations import eligible_release_type
from spotify_manager.domain.album_recommendations import option_rank
from spotify_manager.domain.album_recommendations import option_sort_key
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate


type TrackMatcher = Callable[[Scrobble, object, int], SpotifyTrackMatch | None]
type OptionParser = Callable[
    [object, FoundArtCandidate, int], SpotifyAlbumOption | None
]


def artist_pairs(raw: object) -> tuple[tuple[str, str], ...]:
    """Decode original artist IDs and names with ID fallback before whitespace removal.

    Args:
        raw: Original raw artist list.

    Returns:
        Ordered valid ID/name pairs after original string coercion.
    """
    if not isinstance(raw, list):
        return ()
    pairs = []
    for value in raw:
        if not isinstance(value, dict):
            continue
        identity = str(value.get("id") or "").strip()
        name = str(value.get("name") or identity).strip()
        if identity and name:
            pairs.append((identity, name))
    return tuple(pairs)


def positive_int(raw: object) -> int:
    """Retain original nonnegative integer metadata and the zero fallback.

    Args:
        raw: Original track-count observation.

    Returns:
        Nonnegative integer excluding booleans, or zero for other values.
    """
    return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0


def _primary_album(
    raw: dict[str, object],
    expected: str,
) -> tuple[dict[str, object], tuple[str, str]] | None:
    tracks = artist_pairs(raw.get("artists"))
    album = raw.get("album")
    if not tracks or not isinstance(album, dict):
        return None
    artists = artist_pairs(album.get("artists"))
    if normalize_name(tracks[0][1]) != expected or not artists:
        return None
    if normalize_name(artists[0][1]) != expected:
        return None
    return album, artists[0]


def _option(
    raw: dict[str, object],
    artist: tuple[str, str],
    match: SpotifyTrackMatch,
    rank: int,
) -> SpotifyAlbumOption | None:
    identity = str(raw.get("id") or "").strip()
    uri = str(raw.get("uri") or "").strip()
    name = str(raw.get("name") or "").strip()
    total = positive_int(raw.get("total_tracks"))
    if not identity or not uri or not name:
        return None
    kind = eligible_release_type(raw.get("album_type"), total, name)
    if kind is None:
        return None
    return SpotifyAlbumOption(
        identity,
        uri,
        artist[0],
        artist[1],
        name,
        kind,
        str(raw.get("release_date") or "Unknown"),
        total,
        match.track,
        match.spotify_id,
        rank,
        match.track_similarity,
        match.popularity,
    )


def parse_album_option(
    raw: object,
    candidate: FoundArtCandidate,
    rank: int,
    match_track: TrackMatcher,
) -> SpotifyAlbumOption | None:
    """Check mandatory matching before exact primary credits and release type.

    Args:
        raw: Original raw Spotify search observation.
        candidate: Original ranked Last.fm track candidate.
        rank: Original one-based search position.
        match_track: Existing mandatory artist/title qualification boundary.

    Returns:
        Original eligible plain album or EP observation, or no eligible edition.
    """
    match = match_track(Scrobble(candidate.track, candidate.artist, "", 0), raw, rank)
    if match is None or not isinstance(raw, dict):
        return None
    primary = _primary_album(raw, normalize_name(candidate.artist))
    if primary is None:
        return None
    album, artist = primary
    return _option(album, artist, match, rank)


def parse_album_search(
    response: object,
    candidate: FoundArtCandidate,
    parse_option: OptionParser,
) -> tuple[SpotifyAlbumOption, ...]:
    """Decode and deduplicate original eligible album observations in search order.

    Args:
        response: Original search response.
        candidate: Original ranked candidate.
        parse_option: Existing raw-observation compatibility boundary.

    Returns:
        Preferred observed editions in original deterministic preference order.

    Raises:
        SauvignonSpotifyError: Original response lacks a track-items list.
    """
    page = response.get("tracks") if isinstance(response, dict) else None
    items = page.get("items") if isinstance(page, dict) else None
    if not isinstance(items, list):
        raise SauvignonSpotifyError(
            f"Spotify returned invalid search data for {candidate.artist} - "
            f"{candidate.track}."
        )
    options: dict[str, SpotifyAlbumOption] = {}
    for rank, raw in enumerate(items, start=1):
        option = parse_option(raw, candidate, rank)
        if option is None:
            continue
        previous = options.get(option.spotify_id)
        if previous is None or option_rank(option) > option_rank(previous):
            options[option.spotify_id] = option
    return tuple(sorted(options.values(), key=option_sort_key))


def parse_first_track(response: object, album: SpotifyAlbumOption) -> FirstTrack:
    """Read the first originally playable track without sorting the catalog response.

    Args:
        response: Original album-track response.
        album: Original chosen edition for error context.

    Returns:
        First original valid identity, URI and display name.

    Raises:
        SauvignonSpotifyError: Response is invalid or contains no playable track.
    """
    items = response.get("items") if isinstance(response, dict) else None
    if not isinstance(items, list):
        raise SauvignonSpotifyError(
            f"Spotify returned invalid tracks for {album.artist} - {album.album}."
        )
    for raw in items:
        if not isinstance(raw, dict):
            continue
        identity = str(raw.get("id") or "").strip()
        uri = str(raw.get("uri") or "").strip()
        name = str(raw.get("name") or "").strip()
        if identity and uri and name:
            return FirstTrack(identity, uri, name)
    raise SauvignonSpotifyError(
        f"No playable first track found for {album.artist} - {album.album}."
    )
