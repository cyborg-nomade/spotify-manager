"""Offline Queue neighborhoods used to capture original ranking observations."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotify_manager.client.lastfm import LastFmSimilarArtist
from spotify_manager.domain.queue_values import ArtistSeed
from spotify_manager.routines import the_queue as legacy


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/queue_neighbors.json"
WEEK = date(2026, 8, 7)
NOW = datetime(2026, 8, 8, tzinfo=UTC)
SEEDS = (
    ArtistSeed("Seed A", "seed-a", "recent", 10, 5, 1.25, 1.0),
    ArtistSeed("Seed B", "seed-b", "annual", 10, 5, 1.1, 1.0),
    ArtistSeed("Seed A", "duplicate", "overall", 10, 5, 0.8, 1.0),
)
NEIGHBORS = (
    LastFmSimilarArtist("Beyoncé", 0.9),
    LastFmSimilarArtist("BEYONCE", 0.5),
    LastFmSimilarArtist("", 1.0),
    LastFmSimilarArtist("Heard", 1.0),
    LastFmSimilarArtist("Previous", 1.0),
    LastFmSimilarArtist("Zero", 0.0),
    LastFmSimilarArtist("Negative", -0.5),
    LastFmSimilarArtist("Tie B", 0.7),
    LastFmSimilarArtist("Tie A", 0.7),
)


@dataclass
class Neighbors:
    """Return deterministic neighborhoods while recording real request arguments.

    Args:
        requests: Original artist and limit observations.
    """

    requests: list[tuple[str, int]]

    def similar_artists(
        self, artist: str, *, limit: int = 50
    ) -> tuple[LastFmSimilarArtist, ...]:
        """Observe one read and return the original ordered fixture.

        Args:
            artist: Requested original seed spelling.
            limit: Requested original API limit.

        Returns:
            Deterministic neighborhood, reversed for the second seed.
        """
        self.requests.append((artist, limit))
        return tuple(reversed(NEIGHBORS)) if artist == "Seed B" else NEIGHBORS


def original_outcome(limit: int, week: date) -> object:
    """Observe the compatibility runner without files or network.

    Args:
        limit: Original pool slicing argument, including zero and negatives.
        week: Original explicit listening week.

    Returns:
        JSON-compatible candidates, requests and accepted cache checkpoints.
    """
    reader = Neighbors([])
    cache: dict[str, object] = {"version": 1, "entries": {}}
    with (
        patch.object(legacy, "_load_cache", return_value=cache),
        patch.object(legacy, "_save_cache") as save,
        patch.object(legacy, "previously_added_artist_keys", return_value={"previous"}),
    ):
        result = legacy.gather_artist_recommendations(
            cast(legacy.LastFmReader, reader),
            SEEDS,
            {"heard"},
            candidate_pool_size=limit,
            week_start=week,
            now=NOW,
        )
    outcome = {
        "result": [asdict(candidate) for candidate in result],
        "requests": reader.requests,
        "saves": save.call_count,
        "cache": cache,
    }
    return json.loads(json.dumps(outcome))


def cases() -> list[tuple[str, dict[str, object]]]:
    """Read frozen original ranking and cache observations.

    Returns:
        Named immutable scenario inputs and outcomes.
    """
    raw = cast(dict[str, dict[str, object]], json.loads(FIXTURE.read_text()))
    return list(raw.items())
