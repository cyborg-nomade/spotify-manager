"""Durable New Wine record decoding retains legacy acceptance and error behavior."""

from dataclasses import asdict

import pytest

from spotify_manager.application.new_wine import _finished
from spotify_manager.application.new_wine_state import release_from_record
from spotify_manager.application.new_wine_state import source_from_record
from spotify_manager.application.new_wine_state import track_from_record
from spotify_manager.application.new_wine_values import NewWineStateError
from tests.support.new_wine_memory import ALBUM
from tests.support.new_wine_memory import SOURCE
from tests.support.new_wine_memory import TARGET


@pytest.mark.parametrize("raw", [None, [], "invalid"])
def test_non_record_values_keep_existing_state_errors(raw: object) -> None:
    """Unstructured records fail before constructor decoding.

    Args:
        raw: Non-record serialized value.
    """
    with pytest.raises(NewWineStateError, match="source track"):
        source_from_record(raw)
    with pytest.raises(NewWineStateError, match="release plan"):
        release_from_record(raw)
    if raw is None:
        assert track_from_record(raw) is None
        return
    with pytest.raises(NewWineStateError, match="target track"):
        track_from_record(raw)


def test_source_requires_release_record_but_ignores_unknown_outer_fields() -> None:
    """Outer source records remain tolerant; release construction remains strict."""
    with pytest.raises(NewWineStateError, match="source track"):
        source_from_record({"release": None})
    source = asdict(SOURCE)
    source["extra"] = "future metadata"
    assert source_from_record(source) == SOURCE
    del source["name"]
    with pytest.raises(KeyError, match="name"):
        source_from_record(source)


def test_catalog_constructor_errors_are_not_reclassified() -> None:
    """Missing and unknown catalog fields keep their original TypeError boundary."""
    with pytest.raises(TypeError):
        release_from_record({})
    with pytest.raises(TypeError):
        track_from_record({**asdict(TARGET), "future": True})
    assert release_from_record(asdict(ALBUM)) == ALBUM
    assert track_from_record(asdict(TARGET)) == TARGET


@pytest.mark.parametrize(
    "entries", [[None], [{"status": "pending"}], [{"status": "future"}]]
)
def test_completion_guard_rejects_unfinished_or_malformed_entries(
    entries: list[object],
) -> None:
    """Completion requires an accepted completed/skipped status for every entry.

    Args:
        entries: Incomplete durable sequence.
    """
    assert not _finished(entries)
