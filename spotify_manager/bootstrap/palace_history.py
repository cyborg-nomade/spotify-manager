"""Compose Palace history with original export, clock and random-reader seams."""

from datetime import date
from datetime import datetime
from functools import partial
from pathlib import Path

from spotify_manager.application.palace_history import PalaceHistory
from spotify_manager.domain.palace_values import HistoricalAlbumSelection
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import palace_of_memory as legacy


def _progress(callback: legacy.ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def select_history(
    count: int,
    path: Path,
    today: date | None,
    random: legacy.RandomIndexReader,
    progress: legacy.ProgressCallback | None,
) -> tuple[datetime, date, int, tuple[HistoricalAlbumSelection, ...]]:
    """Bind original history loading, clock timing and optional progress delivery.

    Args:
        count: Original requested album count.
        path: Original history export location.
        today: Original optional effective date.
        random: Original caller-owned index reader.
        progress: Original optional stage presenter.

    Returns:
        Original complete timestamp, cutoff, population and selections.
    """
    return PalaceHistory(
        partial(blast_from_past.load_scrobbles_by_date, path),
        partial(legacy.palace_cutoff, today),
        random,
        partial(_progress, progress),
        blast_from_past.FIRST_ELIGIBLE_DATE,
    ).run(count)
