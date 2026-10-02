"""Protect original Queue record shape failures and permissive constructor values."""

from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.application.queue_values import QueueStateError
from spotify_manager.infrastructure.queue_records import catalog_track
from spotify_manager.infrastructure.queue_records import flush_result
from spotify_manager.infrastructure.queue_records import mapped_artist
from spotify_manager.infrastructure.queue_records import playlist_track
from tests.support.queue_fill import ARTIST
from tests.support.queue_fill import TRACK
from tests.support.queue_flush import SOURCE
from tests.support.queue_flush import FlushObservations


@pytest.mark.parametrize("raw", [None, [], {}, {"release": {}}, {"release": []}])
def test_original_invalid_source_shape(raw: object) -> None:
    """Reject original unconstructable sources without hiding shape failures.

    Args:
        raw: Original invalid source value.
    """
    with pytest.raises(QueueStateError, match="invalid playlist track"):
        playlist_track(raw)


def test_original_source_string_coercions_and_release_values() -> None:
    """Retain outer string coercions while preserving nested constructor tolerance."""
    raw = asdict(SOURCE)
    raw["spotify_id"] = 123
    release = cast(dict[str, object], raw["release"])
    release["total_tracks"] = "legacy count"
    decoded = playlist_track(raw)
    assert decoded.spotify_id == "123"
    assert cast(object, decoded.release.total_tracks) == "legacy count"


@pytest.mark.parametrize("raw", [[], {}, {"unknown": 1}])
def test_original_invalid_target_shape(raw: object) -> None:
    """Keep original target constructor errors at the JSON boundary.

    Args:
        raw: Original invalid target value.
    """
    with pytest.raises(QueueStateError, match="invalid target track"):
        catalog_track(raw)


def test_original_optional_target_and_permissive_values() -> None:
    """Retain absent targets and original dataclass field-value tolerance."""
    assert catalog_track(None) is None
    raw = asdict(TRACK)
    raw["track_number"] = "legacy position"
    decoded = catalog_track(raw)
    assert decoded is not None
    assert cast(object, decoded.track_number) == "legacy position"


@pytest.mark.parametrize("raw", [None, [], {}, {"unknown": 1}])
def test_original_unusable_artist_mapping_is_miss(raw: object) -> None:
    """Keep unconstructable mappings as misses before interaction.

    Args:
        raw: Original unusable mapping value.
    """
    assert mapped_artist(raw) is None


def test_original_mapping_field_values_are_not_strengthened() -> None:
    """Retain original dataclass mapping tolerance at the documented JSON boundary."""
    raw = asdict(ARTIST)
    raw["spotify_id"] = 123
    decoded = mapped_artist(raw)
    assert decoded is not None
    assert cast(object, decoded.spotify_id) == 123


@pytest.mark.parametrize(
    "field", ["top_tracks", "top_liked_tracks", "total_liked_tracks"]
)
@pytest.mark.parametrize("value", [None, "3", True])
def test_original_result_count_validation(field: str, value: object) -> None:
    """Keep original exact integer validation and field-specific error text.

    Args:
        field: Original required count field.
        value: Original invalid count value.
    """
    plan = FlushObservations("advance").plan_record([SOURCE.uri])
    plan[field] = value
    with pytest.raises(QueueStateError) as error:
        flush_result(SOURCE, plan, False)
    assert str(error.value) == f"Queue plan has invalid {field}."


def test_original_completion_field_coercions() -> None:
    """Keep legacy action, optional release and reason string coercions."""
    plan = FlushObservations("promote").plan_record([SOURCE.uri])
    plan.update(action=12, target_release=123, reason=456)
    result = flush_result(SOURCE, plan, True)
    assert cast(str, result.action) == "12"
    assert (result.target_track, result.target_release, result.reason) == (
        "Track",
        "123",
        "456",
    )
    assert result.dry_run
    plan.update(target=None, target_release=0, reason=0)
    result = flush_result(SOURCE, plan, False)
    assert result.target_track is result.target_release is result.reason is None


def test_original_missing_action_remains_key_error() -> None:
    """Preserve the original required-action failure after validating counts."""
    plan = FlushObservations("advance").plan_record([SOURCE.uri])
    del plan["action"]
    with pytest.raises(KeyError, match="action"):
        flush_result(SOURCE, plan, False)
