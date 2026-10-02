"""Compose Genre Reveal with caller-owned synchronous boundary dependencies."""

from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.genre_run import GenreReveal
from spotify_manager.infrastructure.legacy.genre_run import LegacyGenreReveal
from spotify_manager.routines import genre_reveal as legacy


def run_genre_reveal(
    spotify: Spotify,
    slug: str,
    name: str,
    destination: str,
    path: Path,
    reader: legacy.PageReader,
) -> legacy.GenreRevealRunResult:
    """Bind the original source, membership, accepted writes and result presentation.

    Args:
        spotify: Caller-owned Spotify client.
        slug: Original genre identity.
        name: Original display name.
        destination: Original target identity.
        path: Original audit location.
        reader: Original public-page reader.

    Returns:
        Original presented completion outcome after its accepted audit.
    """
    effects = LegacyGenreReveal(spotify, reader, path)
    GenreReveal(effects).run(slug, name, destination)
    return effects.result
