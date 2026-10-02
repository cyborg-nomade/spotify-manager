"""Validate original exact annual source/chart names before planning or creation."""

from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.domain.annual_selection import matching_playlist_ids
from spotify_manager.domain.composers import OwnedPlaylist


def named_playlist(playlists: tuple[OwnedPlaylist, ...], name: str) -> str | None:
    """Resolve the original sole distinct casefold-matching owned identity.

    Args:
        playlists: Original current complete owned playlist facts.
        name: Original exact requested display name.

    Returns:
        Original sole matching identity or none.

    Raises:
        NewYearError: Distinct owned playlists share the requested name.
    """
    matches = matching_playlist_ids(playlists, name)
    if len(matches) > 1:
        raise NewYearError(
            f'Multiple owned playlists named "{name}"; rename the extras.'
        )
    return next(iter(matches), None)


def obsessions_playlist(playlists: tuple[OwnedPlaylist, ...], year: int) -> str:
    """Require the original annual Obsessions source before history rebuilding.

    Args:
        playlists: Original current owned playlist facts.
        year: Original completed source year.

    Returns:
        Original sole matching source identity.

    Raises:
        NewYearError: The original source is missing or ambiguous.
    """
    identity = named_playlist(playlists, f"Obsessions {year}")
    if identity is None:
        raise NewYearError(
            f'Could not find an owned playlist named "Obsessions {year}".'
        )
    return identity
