"""Read original seed snapshots without importing production SDKs or routines."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

from spotify_manager.domain.recommendation_history import TrackHistory
from spotify_manager.domain.recommendation_seeds import FoundArtSeed


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/found_art_seeds.json"


def seed_cases() -> list[dict[str, object]]:
    """Read the original pre-extraction seed inputs and decisions.

    Returns:
        Seven original cases with their provenance retained.
    """
    payload = json.loads(FIXTURE.read_text())
    assert payload["source"] == "f1704d0"
    return cast(list[dict[str, object]], payload["scenarios"])


def _track(record: dict[str, object]) -> TrackHistory:
    key = cast(list[str], record["key"])
    return TrackHistory(
        str(record["artist"]),
        str(record["track"]),
        (key[0], key[1]),
        cast(int, record["play_count"]),
        cast(int, record["recent_play_count"]),
        cast(int, record["annual_play_count"]),
        cast(int, record["last_played_ms"]),
    )


def seed_history(case: dict[str, object]) -> list[TrackHistory]:
    """Reconstruct the original typed listening statistics from one snapshot.

    Args:
        case: Original JSON fixture case.

    Returns:
        Input history in original order, preserving duplicate keys.
    """
    records = cast(list[dict[str, object]], case["history"])
    return [_track(record) for record in records]


def seed_records(seeds: tuple[FoundArtSeed, ...]) -> list[dict[str, object]]:
    """Normalize selected seed tuples to the original JSON fixture representation.

    Args:
        seeds: Selected typed seeds.

    Returns:
        JSON-shaped records, with tuple identities represented as lists.
    """
    records = [asdict(seed) for seed in seeds]
    return cast(list[dict[str, object]], json.loads(json.dumps(records)))
