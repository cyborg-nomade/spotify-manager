"""Compose original genre progress replacement through its acquired state handle."""

from spotify_manager.application.genre_progress import UpdateGenreProgress
from spotify_manager.core.state.compat import RoutineState
from spotify_manager.infrastructure.legacy.genre_progress import LegacyGenreProgress
from spotify_manager.routines import genre_reveal as legacy


def update_genre_progress(
    state: RoutineState, update: legacy.GenreRevealStateUpdate
) -> legacy.GenreRevealState:
    """Keep original Pydantic validation/presentation at the outer state boundary.

    Args:
        state: Original acquired authoritative state handle.
        update: Original validated desired editable fields.

    Returns:
        Original current or accepted presented progress instance.
    """
    effects = LegacyGenreProgress(state)
    UpdateGenreProgress(effects).run(tuple(update.completed), update.hide_done)
    return effects.result
