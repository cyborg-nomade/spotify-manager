"""Capture original Palace dated rankings and Random.org error translations."""

import json
from contextlib import ExitStack
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import palace_of_memory as legacy
from tests.support.queue_neighbors import NOW


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/palace_history.json"
PROFILES = (
    "normal",
    "empty",
    "history-error",
    "random-error",
    "value-error",
    "out-of-range",
    "duplicate-indexes",
    "no-indexes",
)


def plays() -> dict[date, list[Scrobble]]:
    """Build original eligible, ineligible and blank-label historical buckets.

    Returns:
        Complete original unordered history buckets.
    """
    return {
        date(2021, 1, 2): [
            Scrobble("one", "Artist", "Zulu", 1),
            Scrobble("two", "Artist", "Alpha", 2),
        ],
        date(2020, 1, 2): [Scrobble("one", "Artist", "Release", 1)],
        date(2000, 1, 2): [Scrobble("one", "Artist", "Too Early", 1)],
        date(2026, 1, 2): [Scrobble("one", "Artist", "Too Late", 1)],
        date(2022, 1, 2): [Scrobble("one", "Artist", " ", 1)],
    }


@dataclass
class HistoryReads:
    """Observe original history and random boundaries without filesystem or network.

    Args:
        profile: Original configured population or failure behavior.
        second: Original Random.org second used for album rank wraparound.
        trace: Original ordered observations.
    """

    profile: str
    second: int
    trace: list[list[object]] = field(default_factory=list)

    def read(self, path: Path) -> dict[date, list[Scrobble]]:
        """Supply original history or its original export failure.

        Args:
            path: Original export location.

        Returns:
            Original complete history buckets.

        Raises:
            LastFmExportError: The configured original export fails.
        """
        self.trace.append(["history", str(path)])
        if self.profile == "history-error":
            raise blast_from_past.LastFmExportError("history failed")
        return {} if self.profile == "empty" else plays()

    def random(self, population: int, count: int) -> blast_from_past.RandomIndexSet:
        """Supply original ordered indexes, timestamp or random-source failure.

        Args:
            population: Original eligible date count.
            count: Original requested count.

        Returns:
            Original indexes without adding validation to custom readers.

        Raises:
            RandomOrgError: The configured original service fails.
            ValueError: The configured original reader rejects input.
        """
        self.trace.append(["random", population, count])
        if self.profile == "random-error":
            raise blast_from_past.RandomOrgError("random failed")
        if self.profile == "value-error":
            raise ValueError("random input failed")
        indexes = _indexes(self.profile, count, population)
        return blast_from_past.RandomIndexSet(indexes, NOW.replace(second=self.second))

    def progress(self, message: str) -> None:
        """Observe original optional progress.

        Args:
            message: Original visible stage text.
        """
        self.trace.append(["progress", message])


def _indexes(profile: str, count: int, population: int) -> tuple[int, ...]:
    if profile == "out-of-range":
        return (population,)
    if profile == "duplicate-indexes":
        return (1, 1, 0)
    if profile == "no-indexes":
        return ()
    return tuple(range(count))


def original_outcome(profile: str, count: int, second: int) -> object:
    """Observe the original history coordinator before its extraction.

    Args:
        profile: Original configured boundary behavior.
        count: Original requested selection size.
        second: Original generated second.

    Returns:
        JSON-compatible complete original result/error and read trace.
    """
    edge = HistoryReads(profile, second)
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = _run(edge, count)
    except (RuntimeError, IndexError) as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome["trace"] = edge.trace
    return json.loads(json.dumps(outcome, default=str))


def _run(edge: HistoryReads, count: int) -> object:
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(blast_from_past, "load_scrobbles_by_date", edge.read)
        )
        generated, cutoff, available, selected = legacy.select_historical_albums(
            count=count,
            path=Path("history"),
            today=date(2026, 8, 8),
            random_index_reader=edge.random,
            progress_callback=edge.progress,
        )
    return {
        "generated": generated,
        "cutoff": cutoff,
        "available": available,
        "selected": [asdict(album) for album in selected],
    }


def cases() -> list[dict[str, object]]:
    """Read immutable original history-stage observations.

    Returns:
        Original inputs and complete result/error evidence.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text()))
