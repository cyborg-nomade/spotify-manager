"""Compare original malformed Palace catalog observations with named codecs."""

import json
from dataclasses import asdict

import pytest

from spotify_manager.application.palace_values import PalaceOfMemoryDataError
from spotify_manager.domain.palace_albums import preferred_catalog
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.infrastructure.palace_catalog import album_search
from spotify_manager.infrastructure.palace_catalog import first_track
from tests.support.palace_catalog import MAPPED
from tests.support.palace_catalog import cases
from tests.support.palace_catalog import original_outcome


def _outcome(case: dict[str, object]) -> object:
    result: dict[str, object] = {}
    try:
        value = _selection(case)
        result["result"] = asdict(value) if value is not None else None
    except PalaceOfMemoryDataError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    return json.loads(json.dumps(result))


def _selection(case: dict[str, object]) -> SpotifyAlbum | SpotifyFirstTrack | None:
    if case["kind"] == "album":
        return preferred_catalog(
            "Artist", "Release", album_search(case["payload"], "Release")
        )
    return first_track(case["payload"], MAPPED)


@pytest.mark.parametrize("case", cases())
def test_palace_catalog_matches_original_shapes_rank_and_marker_order(
    case: dict[str, object],
) -> None:
    """Retain complete original parsed outcomes and translated catalog errors.

    Args:
        case: Immutable original raw input and observed outcome.
    """
    assert original_outcome(case) == case["outcome"]
    assert _outcome(case) == case["outcome"]
