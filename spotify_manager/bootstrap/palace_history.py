"""Compose Palace history with original export, clock and random-reader seams."""

from datetime import date
from functools import partial
from pathlib import Path

from spotify_manager.application.palace_history import PalaceHistory
from spotify_manager.infrastructure.legacy.dated_history import LegacyDatedHistory
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
    return PalaceHistory(
        LegacyDatedHistory(path, today, random),
        partial(_progress, progress),
        blast_from_past.FIRST_ELIGIBLE_DATE,
    )
