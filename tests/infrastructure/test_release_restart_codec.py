"""Protect tolerant release restart decoding and unknown-field preservation."""

from dataclasses import asdict
from typing import cast

import pytest

from spotify_manager.application.release_check_values import ReleaseCheckStateError
from spotify_manager.application.release_opening import ReleaseState
from spotify_manager.domain.release_check_values import PendingSingle
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.infrastructure import release_state_codec as codec
from tests.support.release_run import ARTIST
from tests.support.release_run import TRACK
from tests.support.release_run import release


ARTIST_RANK = RankedArtist("artist", "Artist", 100, 1)


def test_restart_default_and_additive_legacy_fields_preserve_unknown_data() -> None:
    """Keep the empty document and additive upgrade without changing its input."""
    original = codec.default_state(1)
    assert list(original) == [
        "version",
        "updated_at",
        "last_successful_check_at",
        "last_checked_through",
        "artist_mappings",
        "skipped_artists",
        "processed_releases",
        "pending_singles",
        "active_run",
    ]
    del original["updated_at"]
    del original["skipped_artists"]
    original["operator_field"] = {"nested": []}
    decoded = codec.validate_state(original, 1)
    assert decoded["updated_at"] is None and decoded["skipped_artists"] == {}
    assert "updated_at" not in original and "skipped_artists" not in original
    cast(list[object], cast(ReleaseState, decoded["operator_field"])["nested"]).append(
        "new"
    )
    assert original["operator_field"] == {"nested": []}


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", 2),
        ("artist_mappings", []),
        ("skipped_artists", None),
        ("processed_releases", False),
        ("pending_singles", 1),
        ("active_run", "invalid"),
    ],
)
def test_restart_invalid_section_shape_is_rejected(field: str, value: object) -> None:
    """Retain original validation for every required restart section.

    Args:
        field: Original required section.
        value: Invalid shape or version.
    """
    state = codec.default_state(1)
    state[field] = value
    with pytest.raises(ReleaseCheckStateError, match="Release-check state is invalid"):
        codec.validate_state(state, 1)


@pytest.mark.parametrize("raw", [None, [], "invalid", 1])
def test_restart_nonmapping_document_is_rejected(raw: object) -> None:
    """Reject nonmapping documents before accessing any fields.

    Args:
        raw: Untrusted decoded state.
    """
    with pytest.raises(ReleaseCheckStateError):
        codec.validate_state(raw, 1)


def test_restart_active_dictionary_and_boolean_version_keep_legacy_tolerance() -> None:
    """Do not introduce stronger equality or field-value validation."""
    state = codec.default_state(1)
    state["version"] = True
    state["active_run"] = {"unknown": "retained"}
    assert codec.validate_state(state, 1) == state


@pytest.mark.parametrize("raw", [None, {}, "invalid", 1])
def test_restart_active_ranking_requires_a_list(raw: object) -> None:
    """Retain the original ranking shape error.

    Args:
        raw: Invalid ranking field.
    """
    with pytest.raises(ReleaseCheckStateError, match="ranking is invalid"):
        codec.active_artists({"artists": raw})


@pytest.mark.parametrize("raw", [None, {}, {"unknown": 1}])
def test_restart_active_artist_constructor_errors_keep_their_cause(raw: object) -> None:
    """Translate constructor shape errors without silently discarding frozen artists.

    Args:
        raw: Invalid frozen artist.
    """
    with pytest.raises(ReleaseCheckStateError) as error:
        codec.active_artists({"artists": [raw]})
    assert isinstance(error.value.__cause__, TypeError)


def test_restart_active_ranking_preserves_order_duplicates_and_untyped_values() -> None:
    """Keep tolerant constructor values and repeated ranking observations."""
    raw = asdict(ARTIST_RANK)
    raw["scrobbles"] = "originally accepted"
    artists = codec.active_artists({"artists": [raw, asdict(ARTIST_RANK), raw]})
    assert cast(object, artists[0].scrobbles) == "originally accepted"
    assert artists[1] == ARTIST_RANK and artists[2] == artists[0]
    assert codec.active_artists({"artists": []}) == ()


@pytest.mark.parametrize("raw", [None, [], {}, {"unknown": 1}])
def test_restart_malformed_mapping_returns_no_mapping(raw: object) -> None:
    """Malformed stored mappings can be resolved again.

    Args:
        raw: Invalid stored mapping.
    """
    assert codec.mapped_artist(raw) is None


def test_restart_mapping_retains_constructor_field_values() -> None:
    """Restore valid original fields without inventing new value constraints."""
    assert codec.mapped_artist(asdict(ARTIST)) == ARTIST
    raw = asdict(ARTIST)
    raw["popularity"] = "unknown"
    decoded = codec.mapped_artist(raw)
    assert decoded is not None and cast(object, decoded.popularity) == "unknown"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"artist_key": "artist"},
        {"artist_key": "artist", "release": None, "first_track": None},
        {"artist_key": "artist", "release": asdict(release()), "first_track": {}},
    ],
)
def test_restart_malformed_pending_record_is_ignored(raw: object) -> None:
    """Keep invalid pending records out of reconsideration.

    Args:
        raw: Invalid pending record.
    """
    assert codec.pending_single(raw) is None


def test_restart_pending_single_retains_original_artist_key_string_coercion() -> None:
    """Coerce only the artist key while preserving original nested dataclass values."""
    pending = PendingSingle("artist", release(kind="Single"), TRACK)
    assert codec.pending_single(asdict(pending)) == pending
    raw = asdict(pending)
    raw["artist_key"] = None
    decoded = codec.pending_single(raw)
    assert decoded is not None and decoded.artist_key == "None"
