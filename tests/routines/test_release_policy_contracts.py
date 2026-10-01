"""Freeze original release classification, precision, scope and window decisions."""

import json
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.routines import release_check as legacy


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/release_check_policy.json"
)


def _release(raw: dict[str, object]) -> legacy.ReleaseCandidate:
    return legacy.ReleaseCandidate(
        str(raw["spotify_id"]),
        str(raw["uri"]),
        str(raw["name"]),
        str(raw["release_type"]),
        str(raw["release_date"]),
        str(raw["release_date_precision"]),
        cast(int, raw["total_tracks"]),
        str(raw["primary_artist_id"]),
        str(raw["primary_artist_name"]),
    )


def _cases() -> list[dict[str, object]]:
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text())["cases"])


@pytest.mark.parametrize("case", _cases())
def test_original_release_policy(case: dict[str, object]) -> None:
    """Compare all original classification, precision and special-title decisions.

    Args:
        case: Frozen original input and exact policy output.
    """
    release = _release(cast(dict[str, object], case["release"]))
    interval = legacy.release_date_interval(release)
    actual_interval = [day.isoformat() for day in interval] if interval else None
    rank = cast(int, case["rank"])
    assert actual_interval == case["interval"]
    assert legacy.release_scope_reason(release, rank) == case["reason"]
    assert list(legacy.release_tags(release)) == case["tags"]
    assert list(legacy._release_identity(release)) == case["identity"]
    assert (
        legacy._released_during(release, date(2026, 8, 1), date(2026, 8, 31))
        == case["during"]
    )
    assert legacy._future_record(release, date(2026, 8, 31), rank) == case["future"]


@pytest.mark.parametrize("case", json.loads(FIXTURE.read_text())["types"])
def test_original_release_type(case: dict[str, object]) -> None:
    """Compare original Spotify release-kind coercion and EP title markers.

    Args:
        case: Frozen original type-classification input and output.
    """
    assert (
        legacy._release_type(case["raw"], cast(int, case["count"]), str(case["name"]))
        == case["expected"]
    )
