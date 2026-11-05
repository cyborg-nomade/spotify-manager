"""Verify portable history bytes, cautious audit import and recovery paging."""

import json
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.core.state.definitions import ObjectDefinition
from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.domain.something_old_history import choice_identity
from spotify_manager.infrastructure.async_state import AsyncRoutineState
from spotify_manager.infrastructure.history_playlist_pages import SpotifyHistoryPages
from spotify_manager.infrastructure.persistence import JsonStateStore
from spotify_manager.infrastructure.something_old_choice_audit import read_choice_audit
from spotify_manager.infrastructure.something_old_choice_playlist import (
    read_choice_playlist,
)
from spotify_manager.infrastructure.something_old_choice_schema import (
    SomethingOldChoiceDefinition,
)
from spotify_manager.infrastructure.something_old_choice_storage import (
    SomethingOldChoiceStorage,
)
from tests.domain.test_something_old_history import recorded_choice


def audit_row(choice: ArtistChoice) -> dict[str, object]:
    """Create the legacy successful audit shape without new journal-only fields.

    Args:
        choice: Completed selection evidence.

    Returns:
        Original JSON-compatible audit record.
    """
    return {
        "action": "added",
        "generated_at": choice.chosen_at.isoformat(),
        "playlist_id": choice.playlist_id,
        "playlist_length_before": 0,
        "playlist_length_after": len(choice.track_ids),
        "spotify_artist": {"spotify_id": choice.artist_id, "name": choice.artist_name},
        "artist": {"artist": choice.lastfm_artist},
        "mode": choice.mode,
        "tracks": [{"spotify_id": identity} for identity in choice.track_ids],
        "release": {"spotify_id": choice.release_id, "name": choice.release_name}
        if choice.release_id
        else None,
    }


def _ledger() -> ChoiceLedger:
    choice = recorded_choice()
    return ChoiceLedger(
        choices={choice_identity(choice): choice}, pending={"destination": choice}
    )


def test_history_schema_roundtrips_dates_and_preserves_both_evidence_categories() -> (
    None
):
    """A process restart reads the same completed and unconfirmed records."""
    schema = SomethingOldChoiceDefinition()
    value = schema.encode(_ledger())
    assert schema.decode(json.loads(json.dumps(value))) == _ledger()
    assert schema.validate(value) == value
    empty = schema.default()
    assert empty == {"choices": {}, "pending": {}, "version": 1}


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"version": 2, "choices": {}, "pending": {}},
        {"version": True, "choices": {}, "pending": {}},
        {"version": 1, "choices": [], "pending": {}},
        {"version": 1, "choices": {}, "pending": {}, "future": {}},
    ],
)
def test_history_schema_rejects_unsupported_or_incomplete_namespace(
    raw: object,
) -> None:
    """Bad state cannot silently lose records or be counted as valid history.

    Args:
        raw: Invalid state shape or version.
    """
    with pytest.raises(StateDocumentError):
        SomethingOldChoiceDefinition().decode(raw)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("artist_id", ""),
        ("artist_name", ""),
        ("lastfm_artist", ""),
        ("playlist_id", ""),
        ("mode", "wrong"),
        ("chosen_at", "2026-11-04T10:00:00"),
        ("track_ids", []),
        ("track_ids", [""]),
        ("future", True),
    ],
)
def test_history_schema_rejects_invalid_record_evidence(
    field_name: str, value: object
) -> None:
    """Stored completion requires a stable mapping, valid mode, date and track list.

    Args:
        field_name: Persisted field to invalidate.
        value: Invalid or unrecognized field value.
    """
    schema = SomethingOldChoiceDefinition()
    raw = schema.encode(_ledger())
    records = cast(dict[str, dict[str, object]], raw["choices"])
    next(iter(records.values()))[field_name] = value
    with pytest.raises(StateDocumentError):
        schema.decode(raw)


@pytest.mark.parametrize("kind", ["choices", "pending"])
def test_history_schema_rejects_mismatched_event_or_destination_keys(kind: str) -> None:
    """Record keys cannot redirect completed evidence to another event or playlist.

    Args:
        kind: Completed-event or pending-destination map.
    """
    schema = SomethingOldChoiceDefinition()
    raw = schema.encode(_ledger())
    records = cast(dict[str, object], raw[kind])
    raw[kind] = {"different": next(iter(records.values()))}
    with pytest.raises(StateDocumentError):
        schema.decode(raw)


def test_available_audit_import_keeps_only_complete_applied_stable_id_records(
    tmp_path: Path,
) -> None:
    """Unknown mappings, previews and malformed/partial records are not history.

    Args:
        tmp_path: Isolated legacy audit bytes.
    """
    choice = recorded_choice()
    valid = audit_row(choice)
    rows = [
        valid,
        {**valid, "action": "would add"},
        {**valid, "dry_run": True},
        {**valid, "spotify_artist": None},
        {**valid, "artist": None},
        {**valid, "mode": "unknown"},
        {**valid, "generated_at": "bad"},
        {**valid, "tracks": []},
        {**valid, "tracks": [{}]},
        {**valid, "playlist_length_after": 0},
        {**valid, "playlist_length_before": 1},
        {**valid, "tracks": [{"spotify_id": ""}]},
    ]
    path = tmp_path / "audit.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\nmalformed\n[]\n")
    assert read_choice_audit(path) == (replace(choice, provenance="audit"),)
    assert read_choice_audit(tmp_path / "missing") == ()


def test_unreadable_existing_audit_fails_explicitly(tmp_path: Path) -> None:
    """A damaged file is distinguished from absent historical evidence.

    Args:
        tmp_path: Isolated unreadable audit.
    """
    path = tmp_path / "audit.jsonl"
    path.write_bytes(b"\xff")
    with pytest.raises(SomethingOldError, match="Could not read"):
        read_choice_audit(path)


@dataclass
class PlaylistPages:
    """Script actual raw page boundaries while retaining complete item multiplicity.

    Args:
        responses: Transport pages in observation order.
        offsets: Recorded raw offsets.
    """

    responses: list[object]
    offsets: list[int] = field(default_factory=list)

    async def read(self, offset: int) -> object:
        """Read a scripted page at the actual requested offset.

        Args:
            offset: Raw item offset.

        Returns:
            Scripted raw response.
        """
        self.offsets.append(offset)
        return self.responses.pop(0)


async def test_recovery_membership_retains_duplicates_unreadable_rows_and_offsets() -> (
    None
):
    """A repeated ID or unsupported item cannot be collapsed into false evidence."""
    pages = PlaylistPages(
        [
            {
                "items": [{"item": {"id": "a"}}, {"track": {"id": "a"}}],
                "next": "following",
                "total": 5,
            },
            {
                "items": [None, {"item": {}}, {"item": {"id": "b"}}],
                "next": None,
                "total": 5,
            },
        ]
    )
    result = await read_choice_playlist(cast(SpotifyHistoryPages, pages))
    assert result == ("a", "a", None, None, "b")
    assert pages.offsets == [0, 2]


@pytest.mark.parametrize(
    "responses",
    [
        [None],
        [{"items": None}],
        [{"items": [], "next": "more"}],
        [{"items": [{}], "next": None, "total": 2}],
        [{"items": [{}], "next": "same"}, {"items": [{}], "next": "same"}],
    ],
)
async def test_recovery_membership_rejects_incomplete_or_repeating_pages(
    responses: list[object],
) -> None:
    """Incomplete external reads must never verify a completed append.

    Args:
        responses: Invalid transport/page sequence.
    """
    with pytest.raises(SomethingOldError):
        await read_choice_playlist(cast(SpotifyHistoryPages, PlaylistPages(responses)))


async def test_shared_history_survives_new_service_and_preserves_other_namespaces(
    tmp_path: Path,
) -> None:
    """Actual JSON persistence retains the history across fresh runtime construction.

    Args:
        tmp_path: Isolated shared-state and audit paths.
    """
    path = tmp_path / "state.json"
    service = StateService(JsonStateStore(path))
    other = service.namespace("other", ObjectDefinition())
    other.load()
    other.save({"operator": "preserved"})
    definition = SomethingOldChoiceDefinition()
    access = SomethingOldChoiceStorage(
        AsyncRoutineState(service.namespace("something_old_choices", definition)),
        tmp_path / "audit.jsonl",
        cast(SpotifyClient, object()),
        NoRetry(),
    )
    assert await access.load() == ChoiceLedger()
    await access.save(_ledger())
    restarted = StateService(JsonStateStore(path))
    restored = SomethingOldChoiceStorage(
        AsyncRoutineState(restarted.namespace("something_old_choices", definition)),
        tmp_path / "audit.jsonl",
        cast(SpotifyClient, object()),
        NoRetry(),
    )
    assert await restored.load() == _ledger()
    assert await restored.audit_choices() == ()
    assert restarted.namespace("other", ObjectDefinition()).load() == {
        "operator": "preserved"
    }


@pytest.mark.parametrize(
    "response",
    [
        {"items": [], "next": True},
        {"items": [], "next": None, "total": True},
        {"items": [], "next": None, "total": -1},
        {"items": []},
        {"items": [{}], "next": "extra", "total": 1},
    ],
)
async def test_recovery_requires_consistent_paging_evidence(response: object) -> None:
    """Ambiguous termination or contradictory totals cannot confirm an old append.

    Args:
        response: Invalid complete-page or continuation claim.
    """
    with pytest.raises(SomethingOldError):
        await read_choice_playlist(cast(SpotifyHistoryPages, PlaylistPages([response])))


async def test_recovery_supports_explicit_totals_without_next_links() -> None:
    """The supported total-based paging shape still reads every raw item."""
    pages = PlaylistPages(
        [
            {"items": [{"item": {"id": "a"}}], "total": 2},
            {"items": [{"item": {"id": "b"}}], "total": 2},
        ]
    )
    assert await read_choice_playlist(cast(SpotifyHistoryPages, pages)) == ("a", "b")
    assert pages.offsets == [0, 1]


async def test_invalid_shared_bytes_surface_as_a_history_error(tmp_path: Path) -> None:
    """Corrupted shared storage cannot be silently replaced by empty history.

    Args:
        tmp_path: Isolated invalid state document.
    """
    path = tmp_path / "state.json"
    path.write_text("{invalid")
    namespace = StateService(JsonStateStore(path)).namespace(
        "something_old_choices", SomethingOldChoiceDefinition()
    )
    access = SomethingOldChoiceStorage(
        AsyncRoutineState(namespace),
        tmp_path / "audit",
        cast(SpotifyClient, object()),
        NoRetry(),
    )
    with pytest.raises(SomethingOldError, match="Could not load"):
        await access.load()


async def test_shared_conflicts_preserve_another_writer_without_silent_replacement(
    tmp_path: Path,
) -> None:
    """An obsolete invocation cannot overwrite a newer history checkpoint.

    Args:
        tmp_path: Isolated revision-guarded shared store.
    """
    service = StateService(JsonStateStore(tmp_path / "state.json"))
    definition = SomethingOldChoiceDefinition()
    namespace = service.namespace("something_old_choices", definition)
    access = SomethingOldChoiceStorage(
        AsyncRoutineState(namespace),
        tmp_path / "audit",
        cast(SpotifyClient, object()),
        NoRetry(),
    )
    await access.load()
    peer = service.namespace("something_old_choices", definition)
    peer.load()
    peer.save(definition.encode(_ledger()))
    with pytest.raises(SomethingOldError, match="Could not save"):
        await access.save(ChoiceLedger())
    assert definition.decode(peer.load()) == _ledger()
