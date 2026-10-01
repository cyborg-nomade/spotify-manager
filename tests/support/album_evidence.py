"""Read original immutable album evidence inputs without routines or SDKs."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/sauvignon_evidence.json"
)


@dataclass(frozen=True)
class AlbumEvidenceCase:
    """Original inputs and immutable output oracle for one album evidence scenario.

    Args:
        candidates: Original ordered ranked track pool.
        observations: Original ordered album observations per track title.
        excluded: Original heard or previously added album keys.
        existing: Original represented destination album identities.
        maximum: Original Python-slice boundary.
        expected: Frozen original serialized recommendations.
        events: Frozen original progress and search observations.
    """

    candidates: tuple[FoundArtCandidate, ...]
    observations: dict[str, tuple[SpotifyAlbumOption, ...]]
    excluded: set[AlbumKey]
    existing: set[str]
    maximum: int
    expected: list[dict[str, object]]
    events: list[str]


def _candidate(raw: dict[str, object]) -> FoundArtCandidate:
    key = cast(list[str], raw["key"])
    return FoundArtCandidate(
        str(raw["artist"]),
        str(raw["track"]),
        (key[0], key[1]),
        cast(float, raw["score"]),
        cast(float, raw["best_match"]),
        tuple(cast(list[str], raw["supporting_seeds"])),
        cast(int, raw["base_rank"]),
        cast(float, raw["weekly_rank"]),
    )


def _option(raw: dict[str, object]) -> SpotifyAlbumOption:
    return SpotifyAlbumOption(
        str(raw["spotify_id"]),
        str(raw["uri"]),
        str(raw["artist_id"]),
        str(raw["artist"]),
        str(raw["album"]),
        str(raw["release_type"]),
        str(raw["release_date"]),
        cast(int, raw["total_tracks"]),
        str(raw["source_track"]),
        str(raw["source_track_id"]),
        cast(int, raw["search_rank"]),
        cast(float, raw["track_similarity"]),
        cast(int | None, raw["track_popularity"]),
    )


def _observations(
    raw: dict[str, list[dict[str, object]]],
) -> dict[str, tuple[SpotifyAlbumOption, ...]]:
    result = {}
    for title, options in raw.items():
        result[title] = tuple(_option(option) for option in options)
    return result


def read_case(name: str) -> AlbumEvidenceCase:
    """Decode one trusted immutable pre-extraction evidence snapshot.

    Args:
        name: Original frozen scenario name.

    Returns:
        Typed original inputs and serialized output oracle.

    Raises:
        KeyError: A fixture field or scenario is missing.
        OSError: The immutable fixture cannot be read.
        ValueError: The fixture JSON cannot be decoded.
    """
    snapshot = json.loads(FIXTURE.read_text())["cases"][name]
    raw = snapshot["input"]
    candidates = tuple(_candidate(item) for item in raw["candidates"])
    excluded = set()
    for artist, album in raw["excluded"]:
        excluded.add((artist, album))
    return AlbumEvidenceCase(
        candidates,
        _observations(raw["observations"]),
        excluded,
        set(raw["existing"]),
        int(raw["maximum"]),
        snapshot["recommendations"],
        snapshot["events"],
    )


def recommendation_records(
    items: tuple[AlbumRecommendation, ...],
) -> list[dict[str, object]]:
    """Project recommendation values into the original immutable JSON shape.

    Args:
        items: Original ranked recommendation values.

    Returns:
        JSON-compatible original model fields, including nested preferred editions.
    """
    records = [asdict(item) for item in items]
    return cast(list[dict[str, object]], json.loads(json.dumps(records)))
