"""Original ID precedence, exact-search selection and live membership stages."""

from collections.abc import Callable

from spotify_manager.application.lookup_effects import AlbumLookup
from spotify_manager.application.lookup_effects import ArtistLookup
from spotify_manager.application.lookup_effects import TrackLookup
from spotify_manager.domain import lookup_selection as selection
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.lookup_values import SpotifyLookupResponseError


def artist(
    deps: ArtistLookup, name: str | None, identifier: str | None
) -> tuple[str, str]:
    """Retain original direct-ID precedence before exact name selection.

    Args:
        deps: Original direct and search reads.
        name: Original optional exact reference.
        identifier: Original direct identity.

    Returns:
        Original complete unique artist identity.

    Raises:
        ValueError: No original reference is supplied.
        SpotifyLookupResponseError: Original direct identity is incomplete.
        LookupError: Original exact resolution fails or is ambiguous.
    """
    if not name and not identifier:
        raise ValueError("provide name or artist_id")
    if identifier:
        identity = deps.direct(identifier)
        if identity is None:
            raise SpotifyLookupResponseError(
                f"Spotify returned invalid artist data for {identifier!r}."
            )
        return identity
    assert name is not None
    return selection.artist(deps.search(name), name)


def album(
    deps: AlbumLookup, name: str | None, identifier: str | None, artist: str | None
) -> tuple[str, str, str | None]:
    """Retain original ID precedence and delayed final metadata validation.

    Args:
        deps: Original direct and search observations.
        name: Original optional exact reference.
        identifier: Original direct identity.
        artist: Original optional primary-artist constraint.

    Returns:
        Original complete unique album identity and display facts.

    Raises:
        ValueError: No original reference is supplied.
        SpotifyLookupResponseError: Original selected metadata is incomplete.
        LookupError: Original exact resolution fails or is ambiguous.
    """
    if not name and not identifier:
        raise ValueError("provide name or album_id")
    if identifier:
        return validated_album(deps.direct(identifier))
    assert name is not None
    candidates = deps.search(name, artist)
    return validated_album(selection.live_album(candidates, name, artist))


def validated_album(candidate: LiveAlbumCandidate) -> tuple[str, str, str | None]:
    """Validate original selected identity after search ambiguity has been resolved.

    Args:
        candidate: Original selected metadata.

    Returns:
        Original trimmed final identity and display facts.

    Raises:
        SpotifyLookupResponseError: The original selected ID or name is empty.
    """
    name = candidate.name.strip()
    if not candidate.spotify_id or not name:
        raise SpotifyLookupResponseError("Spotify returned incomplete album data.")
    return candidate.spotify_id, name, candidate.primary_artist or None


def track(deps: TrackLookup, name: str | None, identifier: str | None) -> ResolvedTrack:
    """Retain original direct-ID precedence before primary-artist disambiguation.

    Args:
        deps: Original direct and search reads.
        name: Original optional title.
        identifier: Original direct identity.

    Returns:
        Original unique primary-artist representative.

    Raises:
        ValueError: No original reference is provided.
        LookupError: Original title selection fails or is ambiguous.
    """
    if not name and not identifier:
        raise ValueError("provide name or track_id")
    if identifier:
        return deps.direct(identifier)
    assert name is not None
    return selection.track(deps.search(name), name)


def liked_statuses(
    ids: list[str], contains: Callable[[list[str]], object], batch_size: int
) -> dict[str, bool]:
    """Retain original duplicate requests and last-observed identity statuses.

    Args:
        ids: Original ordered identities, including duplicates.
        contains: Original fresh membership request.
        batch_size: Original conservative membership batch size.

    Returns:
        Original last status for each identity at its first encounter position.

    Raises:
        SpotifyLookupResponseError: Original response shape or size is invalid.
    """
    liked = {}
    for start in range(0, len(ids), batch_size):
        batch = ids[start : start + batch_size]
        response = contains(batch)
        if not isinstance(response, list) or len(response) != len(batch):
            raise SpotifyLookupResponseError(
                "Spotify returned invalid Liked Songs statuses."
            )
        for identifier, saved in zip(batch, response, strict=True):
            liked[identifier] = bool(saved)
    return liked
