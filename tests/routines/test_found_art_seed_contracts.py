"""Exact seed decisions captured from the original routine at f1704d0."""

from datetime import date
from typing import cast

import pytest

from spotify_manager.routines import found_art
from tests.support.recommendation_seeds import seed_cases
from tests.support.recommendation_seeds import seed_history
from tests.support.recommendation_seeds import seed_records


CASES = seed_cases()


@pytest.mark.parametrize("case", CASES, ids=[str(case["name"]) for case in CASES])
def test_seed_decisions_match_original_snapshots(case: dict[str, object]) -> None:
    """Preserve original sources, scores, ordering, duplicates and diversity errors.

    Args:
        case: Original input and decisions captured before extraction.
    """
    history = seed_history(case)
    count = cast(int, case["seed_count"])
    week = date.fromisoformat(str(case["week_start"]))
    if "error" in case:
        with pytest.raises(found_art.FoundArtStateError) as error:
            found_art.select_seed_tracks(history, seed_count=count, week_start=week)
        assert str(error.value) == case["error"]
        return
    seeds = found_art.select_seed_tracks(history, seed_count=count, week_start=week)
    assert seed_records(seeds) == case["seeds"]
