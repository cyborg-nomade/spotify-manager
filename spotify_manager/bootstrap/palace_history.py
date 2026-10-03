"""Compose Palace history with original export, clock and random-reader seams."""

from datetime import date
from functools import partial
from pathlib import Path

from spotify_manager.application.palace_history import PalaceHistory
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import palace_of_memory as legacy


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def palace_history(
    path: Path,
    today: date | None,
    random: legacy.RandomIndexReader,
    progress: legacy.ProgressCallback | None,
) -> PalaceHistory:
    """Construct the invocation dependencies without executing the use case.

    Args:
        path: Original history export location.
        today: Original optional effective date.
        random: Original caller-owned index reader.
        progress: Original optional stage presenter.

    Returns:
        The configured application dependencies or workflow.
    """
    from spotify_manager.routines.blast_from_past import load_scrobbles_by_date
    from spotify_manager.routines.palace_of_memory import palace_cutoff

    return PalaceHistory(
        partial(load_scrobbles_by_date, path),
        partial(palace_cutoff, today),
        random,
        partial(_progress, progress),
        blast_from_past.FIRST_ELIGIBLE_DATE,
    )
