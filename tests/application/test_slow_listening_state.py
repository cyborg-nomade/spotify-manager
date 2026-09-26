"""Durable Slow Listening reconstruction retains original tolerant boundaries."""

from dataclasses import asdict

import pytest

from spotify_manager.application.slow_listening_state import release_from_record
from spotify_manager.application.slow_listening_state import result_from_plan
from spotify_manager.application.slow_listening_state import source_from_record
from spotify_manager.application.slow_listening_state import track_from_record
from spotify_manager.application.slow_listening_values import SlowListeningStateError
from tests.support.slow_listening_memory import FIRST
from tests.support.slow_listening_memory import SOURCE
from tests.support.slow_listening_memory import TARGET


@pytest.mark.parametrize("raw", [None, [], {"release": None}])
def test_source_requires_a_mapping_and_release(raw: object) -> None:
    """Retain the explicit source shape error before constructor validation.

    Args:
        raw: Invalid serialized marker.
    """
    with pytest.raises(SlowListeningStateError, match="invalid source"):
        source_from_record(raw)


@pytest.mark.parametrize("raw", [[], "bad"])
def test_non_null_targets_and_releases_require_mappings(raw: object) -> None:
    """Retain the two distinct public state error messages.

    Args:
        raw: Invalid serialized target or release.
    """
    with pytest.raises(SlowListeningStateError, match="invalid target"):
        track_from_record(raw)
    with pytest.raises(SlowListeningStateError, match="invalid release"):
        release_from_record(raw)


def test_saved_values_round_trip_and_keep_optional_absence() -> None:
    """Typed constructors preserve every stored field and optional null."""
    assert source_from_record(asdict(SOURCE)) == SOURCE
    assert track_from_record(asdict(TARGET)) == TARGET
    assert release_from_record(asdict(FIRST)) == FIRST
    assert track_from_record(None) is None
    assert release_from_record(None) is None


def test_missing_constructor_fields_still_raise_type_error() -> None:
    """The migration must not silently default incomplete durable records."""
    with pytest.raises(TypeError):
        track_from_record({})
    with pytest.raises(TypeError):
        release_from_record({})
    with pytest.raises(TypeError):
        source_from_record({"release": {}})


def test_result_ignores_non_list_skipped_labels() -> None:
    """Legacy skipped labels must be a list; other containers remain ignored."""
    result = result_from_plan(
        SOURCE, {"action": "skip", "skipped_candidates": ("one",)}, dry_run=True
    )
    assert result.skipped_candidates == ()
    assert result.target_track is None and result.target_release is None
