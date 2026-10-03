"""Invoke genre reveal use cases for CLI and HTTP features."""

from pathlib import Path as Path

from spotipy import Spotify as Spotify

from spotify_manager.application.genre_run import GenreReveal as GenreReveal
from spotify_manager.application.genre_values import (
    GenreRevealCompleteError as GenreRevealCompleteError,
)
from spotify_manager.application.genre_values import (
    GenreRevealConfigError as GenreRevealConfigError,
)
from spotify_manager.application.genre_values import (
    GenreRevealLogError as GenreRevealLogError,
)
from spotify_manager.application.genre_values import (
    GenreRevealSourceError as GenreRevealSourceError,
)
from spotify_manager.application.genre_values import (
    GenreRevealStateError as GenreRevealStateError,
)
from spotify_manager.domain.genres import GenreRouteEntry as GenreRouteEntry
from spotify_manager.infrastructure.genre_models import (
    GenreRevealRunResult as GenreRevealRunResult,
)
from spotify_manager.infrastructure.legacy.genre_run import (
    LegacyGenreReveal as LegacyGenreReveal,
)
from spotify_manager.routines.genre_reveal import DEFAULT_LOG_PATH as DEFAULT_LOG_PATH
from spotify_manager.routines.genre_reveal import (
    DEFAULT_STATE_PATH as DEFAULT_STATE_PATH,
)
from spotify_manager.routines.genre_reveal import PageReader as PageReader
from spotify_manager.routines.genre_reveal import _default_state as _default_state
from spotify_manager.routines.genre_reveal import (
    first_incomplete_genre as first_incomplete_genre,
)
from spotify_manager.routines.genre_reveal import (
    load_genre_reveal_state as load_genre_reveal_state,
)
from spotify_manager.routines.genre_reveal import (
    mark_genre_completed as mark_genre_completed,
)
from spotify_manager.routines.genre_reveal import (
    parse_destination_playlist_id as parse_destination_playlist_id,
)
from spotify_manager.routines.genre_reveal import read_public_page as read_public_page
from spotify_manager.routines.genre_reveal import validate_state as validate_state


def process_next_genre(
    sp: Spotify,
    slug: str,
    name: str,
    destination_playlist_id: str,
    *,
    log_path: Path = DEFAULT_LOG_PATH,
    page_reader: PageReader = read_public_page,
) -> GenreRevealRunResult:
    """Save one genre playlist and copy its first ten missing tracks.

    Args:
        sp: Caller-owned synchronous Spotify client.
        slug: Original genre identity.
        name: Original display name.
        destination_playlist_id: Original target identity.
        log_path: Original audit location.
        page_reader: Original public-page reader.

    Returns:
        Original presented completion outcome after its accepted audit.

    Raises:
        GenreRevealSourceError: Original source discovery fails.
        GenreRevealLogError: Original completion audit cannot be written.
        ValidationError: Original request values are invalid.
    """
    effects = LegacyGenreReveal(sp, page_reader, log_path)
    GenreReveal(effects).run(slug, name, destination_playlist_id)
    return effects.result
