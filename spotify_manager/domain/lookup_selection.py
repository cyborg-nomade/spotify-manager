"""Original exact identity, edition fallback and primary-artist tie rules."""

from collections.abc import Sequence

from spotify_manager.domain.history import normalize_name
from spotify_manager.domain.history_matching import name_similarity
from spotify_manager.domain.lookup_values import AlbumNotFoundError
from spotify_manager.domain.lookup_values import AmbiguousAlbumError
from spotify_manager.domain.lookup_values import AmbiguousArtistError
from spotify_manager.domain.lookup_values import AmbiguousTrackError
from spotify_manager.domain.lookup_values import ArtistNotFoundError
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.lookup_values import SavedAlbum
from spotify_manager.domain.lookup_values import TrackNotFoundError


def exact_name(value: str) -> str:
    """Normalize the original exact album/artist lookup key.

    Args:
        value: Original display reference.

    Returns:
        Original trimmed and case-folded key, preserving accents.
    """
    return value.strip().casefold()


def artist(identities: Sequence[tuple[str, str]], name: str) -> tuple[str, str]:
    """Select one exact identity, deduplicating full identity pairs.

    Args:
        identities: Original parsed artist identities.
        name: Original exact reference.

    Returns:
        Original unique identity.

    Raises:
        ArtistNotFoundError: No identity matches.
        AmbiguousArtistError: Multiple distinct identity pairs match.
    """
    matches: dict[tuple[str, str], None] = {}
    expected = exact_name(name)
    for identity in identities:
        if exact_name(identity[1]) == expected:
            matches[identity] = None
    if not matches:
        raise ArtistNotFoundError(f"No exact Spotify artist named {name!r} was found.")
    if len(matches) > 1:
        raise artist_ambiguity(list(matches), name)
    return next(iter(matches))


def artist_ambiguity(matches: list[tuple[str, str]], name: str) -> AmbiguousArtistError:
    """Build the original ordered artist disambiguation request.

    Args:
        matches: Original distinct matching identity pairs.
        name: Original reference.

    Returns:
        Original error and complete candidates.
    """
    candidates = []
    for identifier, display in matches:
        candidates.append({"artist": display, "id": identifier})
    return AmbiguousArtistError(
        f"Spotify returned {len(matches)} exact artists named {name!r}; "
        "use the Spotify artist ID to disambiguate.",
        candidates,
    )


def local_album(
    albums: Sequence[SavedAlbum],
    name: str | None,
    identifier: str | None,
    artist: str | None,
) -> tuple[str, str | None, str | None]:
    """Resolve original saved-album facts with ID precedence and last-value ties.

    Args:
        albums: Original ordered saved album observations.
        name: Original optional exact name.
        identifier: Original direct identity, taking precedence.
        artist: Original optional exact primary-artist constraint.

    Returns:
        Original identity, name and artist, including unsaved direct identities.

    Raises:
        ValueError: No original lookup reference is supplied.
        AlbumNotFoundError: No name matches.
        AmbiguousAlbumError: Multiple distinct saved identities match.
    """
    if not name and not identifier:
        raise ValueError("provide an album name or album_id")
    if identifier:
        return local_album_id(albums, identifier)
    assert name is not None
    matches = local_album_matches(albums, name, artist)
    if not matches:
        suffix = f" by {artist!r}" if artist else ""
        raise AlbumNotFoundError(
            f"No saved album named {name!r}{suffix}. "
            "Pass album_id to evaluate one you have not saved."
        )
    if len(matches) > 1:
        raise local_album_ambiguity(matches, name)
    selected = next(iter(matches.values()))
    return selected.spotify_id, selected.album, selected.artist


def local_album_id(
    albums: Sequence[SavedAlbum], identifier: str
) -> tuple[str, str | None, str | None]:
    """Retain the first direct identity match and unsaved-ID fallback.

    Args:
        albums: Original ordered saved observations.
        identifier: Original direct identity.

    Returns:
        Original matching display facts or absent facts for an unsaved ID.
    """
    for album in albums:
        if album.spotify_id == identifier:
            return identifier, album.album, album.artist
    return identifier, None, None


def local_album_matches(
    albums: Sequence[SavedAlbum], name: str, artist: str | None
) -> dict[str, SavedAlbum]:
    """Retain last values at each identity's first encounter position.

    Args:
        albums: Original ordered saved observations.
        name: Original exact name.
        artist: Original optional primary-artist reference.

    Returns:
        Original matching identity map.
    """
    matches = {}
    for album in albums:
        if exact_name(album.album) != exact_name(name):
            continue
        if artist and exact_name(album.artist) != exact_name(artist):
            continue
        matches[album.spotify_id] = album
    return matches


def local_album_ambiguity(
    matches: dict[str, SavedAlbum], name: str
) -> AmbiguousAlbumError:
    """Build original saved-album ambiguity with complete display facts.

    Args:
        matches: Original ordered unique observations.
        name: Original reference.

    Returns:
        Original ambiguity error and candidates.
    """
    candidates = []
    for album in matches.values():
        candidates.append(
            {"album": album.album, "artist": album.artist, "id": album.spotify_id}
        )
    return AmbiguousAlbumError(
        f"{len(matches)} saved albums named {name!r}; "
        "disambiguate with artist or album_id.",
        candidates,
    )


def matching_tracks(tracks: Sequence[ResolvedTrack], name: str) -> list[ResolvedTrack]:
    """Prefer exact titles before accepting recognized edition suffixes.

    Args:
        tracks: Original parsed search candidates.
        name: Original exact title.

    Returns:
        Original exact matches or edition matches when no exact title exists.
    """
    exact = []
    expected = normalize_name(name)
    for track in tracks:
        if normalize_name(track.name) == expected:
            exact.append(track)
    if exact:
        return exact
    matches = []
    for track in tracks:
        if name_similarity(name, track.name) == 1.0:
            matches.append(track)
    return matches


def track(tracks: Sequence[ResolvedTrack], name: str) -> ResolvedTrack:
    """Choose the most popular first-credit representative, keeping first ties.

    Args:
        tracks: Original parsed search candidates.
        name: Original title.

    Returns:
        Original unique primary-artist representative.

    Raises:
        TrackNotFoundError: No exact or recognized edition match exists.
        AmbiguousTrackError: Multiple primary-artist groups match.
    """
    matches = matching_tracks(tracks, name)
    if not matches:
        raise TrackNotFoundError(f"No exact Spotify track named {name!r} was found.")
    representatives: dict[str, ResolvedTrack] = {}
    for candidate in matches:
        key = normalize_name(candidate.primary_artist)
        current = representatives.get(key)
        if current is None or candidate.popularity > current.popularity:
            representatives[key] = candidate
    if len(representatives) > 1:
        raise track_ambiguity(list(representatives.values()), name)
    return next(iter(representatives.values()))


def track_ambiguity(tracks: Sequence[ResolvedTrack], name: str) -> AmbiguousTrackError:
    """Build the original title ambiguity between primary artists.

    Args:
        tracks: Original artist representatives.
        name: Original reference.

    Returns:
        Original ambiguity error and complete candidates.
    """
    candidates = []
    for track in tracks:
        candidates.append(
            {
                "track": track.name,
                "artist": track.primary_artist,
                "album": track.album or "",
                "id": track.spotify_id,
            }
        )
    return AmbiguousTrackError(
        f"Spotify returned {len(tracks)} exact tracks named {name!r}; "
        "use a Spotify track link or ID to disambiguate.",
        candidates,
    )


def is_primary_credit(credit: str | None, artist: str) -> bool:
    """Qualify catalog membership using only the first credited artist.

    Args:
        credit: Original first credit or none.
        artist: Original resolved identity.

    Returns:
        Whether the original primary-credit qualification passes.
    """
    return credit == artist


def live_album(
    candidates: Sequence[LiveAlbumCandidate], name: str, artist: str | None
) -> LiveAlbumCandidate:
    """Retain exact live filters, last-value identity ties and original ambiguity.

    Args:
        candidates: Original parsed live observations.
        name: Original exact album reference.
        artist: Original optional primary-artist reference.

    Returns:
        Original unique candidate, before final completeness validation.

    Raises:
        AlbumNotFoundError: No original exact candidate exists.
        AmbiguousAlbumError: Multiple original identities qualify.
    """
    expected = exact_name(name)
    expected_artist = exact_name(artist) if artist else None
    matches: dict[str, LiveAlbumCandidate] = {}
    for candidate in candidates:
        if exact_name(candidate.name) != expected:
            continue
        if (
            expected_artist is not None
            and exact_name(candidate.primary_artist or "") != expected_artist
        ):
            continue
        if candidate.spotify_id:
            matches[candidate.spotify_id] = candidate
    if not matches:
        suffix = f" by {artist!r}" if artist else ""
        raise AlbumNotFoundError(
            f"No exact Spotify album named {name!r}{suffix} was found."
        )
    if len(matches) > 1:
        raise live_album_ambiguity(matches, name)
    return next(iter(matches.values()))


def live_album_ambiguity(
    matches: dict[str, LiveAlbumCandidate], name: str
) -> AmbiguousAlbumError:
    """Retain original untrimmed ambiguity display names in identity order.

    Args:
        matches: Original unique matching observations.
        name: Original exact reference.

    Returns:
        Original complete ambiguity error.
    """
    candidates = []
    for identifier, candidate in matches.items():
        candidates.append(
            {
                "album": candidate.name or name,
                "artist": candidate.display_artist,
                "id": identifier,
            }
        )
    return AmbiguousAlbumError(
        f"Spotify returned {len(matches)} exact albums named {name!r}; "
        "disambiguate with artist or album ID.",
        candidates,
    )
