"""Compare tolerant artist-review catalog records with original raw observations."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.infrastructure import artist_review_records as records


def _cases() -> list[dict[str, object]]:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures/refactor/artist_review_records.json"
    )
    return cast(list[dict[str, object]], json.loads(path.read_text()))


def _outcome(case: dict[str, object]) -> object:
    raw = case["raw"]
    if case["kind"] == "track":
        track = records.track_candidate(raw, 3, "a")
        return asdict(track) if track else None
    if case["kind"] == "release":
        release = records.release_candidate(raw, 3, "a")
        return asdict(release) if release else None
    item = cast(dict[str, object], raw)
    if case["kind"] == "artists":
        return records.artist_ids(item)
    if case["kind"] == "name":
        return records.first_artist_name(item)
    return records.release_type(item)


@pytest.mark.parametrize("case", _cases())
def test_raw_review_record_matches_original_tolerance(case: dict[str, object]) -> None:
    """Retain associated credits, whitespace guards, booleans and raw type casing.

    Args:
        case: Immutable original raw record and complete parser output.
    """
    assert json.loads(json.dumps(_outcome(case))) == case["outcome"]
