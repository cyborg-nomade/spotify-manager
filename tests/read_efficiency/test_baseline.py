"""Keep the original serial catalog implementation as the differential oracle."""

import json
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.infrastructure.lookup_catalog import primary_tracks
from tests.read_efficiency.catalog_memory import CatalogPages
from tests.read_efficiency.catalog_memory import release_ids


BASELINE = Path(__file__).with_name("fixtures") / "baseline.json"


def original_budget(name: str) -> tuple[int, int, int]:
    """Read the pre-change measurements recorded against the Item 9 merge.

    Args:
        name: Exact synthetic scenario recorded before the optimization.

    Returns:
        Original request count, peak overlap and unique result count.
    """
    payload = cast(dict[str, object], json.loads(BASELINE.read_text()))
    measurements = cast(dict[str, dict[str, int]], payload["measurements"])
    values = measurements[name]
    return values["requests"], values["peak_reads"], values["results"]


@pytest.mark.parametrize(
    "scenario, repetitions",
    [
        ("80_distinct_album_ids", 1),
        ("80_album_ids_repeated_twice", 2),
        ("80_identical_album_ids", 0),
    ],
)
async def test_original_catalog_request_budget(scenario: str, repetitions: int) -> None:
    """Measure the unchanged serial request count and original result ordering.

    Args:
        scenario: Exact pre-change measurement from the committed fixture.
        repetitions: Complete catalog repeats, or zero for identical IDs.
    """
    identifiers = release_ids(80) * repetitions if repetitions else ["same"] * 80
    source = CatalogPages()
    result = await primary_tracks(source, "artist", identifiers, 20)
    assert result == list(dict.fromkeys(identifiers))
    assert (len(source.calls), source.peak, len(result)) == original_budget(scenario)
    assert source.active == 0
