"""Compose Palace history with original export, clock and random-reader seams."""

from datetime import date
from pathlib import Path

from spotify_manager.application.palace_history import PalaceHistory
from spotify_manager.application.ports.runtime import OptionalMessages
from spotify_manager.infrastructure.legacy.dated_history import LegacyDatedHistory
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import palace_of_memory as legacy


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
        OptionalMessages(progress),
        blast_from_past.FIRST_ELIGIBLE_DATE,
    )
