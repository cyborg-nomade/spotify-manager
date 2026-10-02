"""Queue 3 snapshots and durable records retain original coercions and routing."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import cast

import pytest
from pydantic import ValidationError

from spotify_manager.application.queue_3_state import new_run
from spotify_manager.application.queue_3_state import release_from_record
from spotify_manager.application.queue_3_state import result_from_plan
from spotify_manager.application.queue_3_state import source_from_record
from spotify_manager.application.queue_3_state import track_from_record
from spotify_manager.application.queue_3_values import Queue3StateError
from spotify_manager.application.release_evaluation import evaluate_release
from spotify_manager.domain.catalog import PlaylistTrack
from tests.support.listening_values import playlist_track
from tests.support.listening_values import release_track
from tests.support.listening_values import studio_release


RELEASE = studio_release("album", "Album")
SOURCE = playlist_track("source", RELEASE)
TARGET = release_track("target")
NOW = datetime(2026, 9, 28, tzinfo=UTC)


@dataclass
class SnapshotClock:
    """Expose distinct timestamps for run identity and creation time.

    Args:
        reads: Accepted clock reads.
    """

    reads: list[datetime] = field(default_factory=list)

    def now(self) -> datetime:
        """Return the next timestamp and record its observation.

        Returns:
            Initial time plus one second per previous read.
        """
        value = NOW + timedelta(seconds=len(self.reads))
        self.reads.append(value)
        return value


@pytest.mark.parametrize("raw", [None, [], {}, {"release": None}])
def test_source_rejects_nonrecords_with_original_error(raw: object) -> None:
    """Only source/release mapping presence is checked before constructor decoding.

    Args:
        raw: Invalid source record shape.
    """
    with pytest.raises(
        Queue3StateError, match="Queue 3 run has an invalid source track"
    ):
        source_from_record(raw)


def test_source_coerces_marker_fields_but_preserves_release_constructor_values() -> (
    None
):
    """Legacy source fields retain string coercion and tolerate unknown outer fields."""
    raw = asdict(SOURCE)
    raw.update(spotify_id=12, name=None, unknown=True)
    parsed = source_from_record(raw)
    assert parsed.spotify_id == "12" and parsed.name == "None"
    assert parsed.release == SOURCE.release
    raw.pop("uri")
    with pytest.raises(KeyError, match="uri"):
        source_from_record(raw)


def test_source_release_constructor_does_not_silently_drop_unknown_fields() -> None:
    """Unexpected nested fields remain explicit constructor errors."""
    raw = asdict(SOURCE)
    raw["release"]["unknown"] = True
    with pytest.raises(TypeError, match="unknown"):
        source_from_record(raw)


@pytest.mark.parametrize("raw", [False, [], "invalid"])
def test_optional_records_reject_non_null_nonrecords(raw: object) -> None:
    """Targets and selected releases retain separate Queue 3 state errors.

    Args:
        raw: Non-null invalid record shape.
    """
    with pytest.raises(Queue3StateError, match="invalid release"):
        release_from_record(raw)
    with pytest.raises(Queue3StateError, match="invalid target track"):
        track_from_record(raw)


def test_optional_records_roundtrip_and_keep_constructor_failures() -> None:
    """Optional records retain constructor values and nullable fields."""
    assert release_from_record(None) is None and track_from_record(None) is None
    assert release_from_record(asdict(RELEASE)) == RELEASE
    assert track_from_record(asdict(TARGET)) == TARGET
    with pytest.raises(TypeError):
        release_from_record({})
    with pytest.raises(TypeError):
        track_from_record({})


@pytest.mark.parametrize(
    "action,expected",
    [
        ("composer_advance", "composer playlist"),
        ("next_release", "next release"),
        ("unknown", "unknown"),
    ],
)
def test_result_projection_preserves_actions_and_truthy_optional_fields(
    action: str,
    expected: str,
) -> None:
    """Saved plans keep tolerant unknown actions and original public action labels.

    Args:
        action: Durable action string.
        expected: Original public action label.
    """
    evaluation = evaluate_release(SOURCE.release, (TARGET,), {"target": True})
    plan: dict[str, object] = {
        "action": action,
        "target": asdict(TARGET),
        "target_release": asdict(RELEASE),
        "evaluation": evaluation.model_dump(mode="json"),
        "composer_playlist_name": 12,
        "reason": True,
    }
    result = result_from_plan(SOURCE, plan, artist_name="Logical", dry_run=True)
    assert result.action == expected and result.artist == "Logical"
    assert result.target_track == "target" and result.target_release == "Album"
    assert result.album_decision == "keep" and result.album_liked_tracks == 1
    assert result.album_total_tracks == 1 and result.dry_run is True
    assert result.composer_playlist == "12" and result.reason == "True"


def test_result_projection_ignores_nonrecord_evaluation_and_falsy_labels() -> None:
    """Empty optional fields stay absent; invalid evaluation records still fail."""
    plan: dict[str, object] = {"action": "skip", "evaluation": False, "reason": 0}
    result = result_from_plan(SOURCE, plan, artist_name="Artist", dry_run=False)
    assert result.target_track is None and result.target_release is None
    assert result.album_decision is None and result.album_liked_tracks is None
    assert result.album_total_tracks is None and result.composer_playlist is None
    assert result.reason is None
    plan["evaluation"] = {}
    with pytest.raises(ValidationError):
        result_from_plan(SOURCE, plan, artist_name="Artist", dry_run=False)


def test_snapshot_uses_last_valid_route_and_separate_clock_reads() -> None:
    """Last valid route wins even when its logical ID is an empty string."""
    clock = SnapshotClock()
    routes: dict[str, object] = {
        "first": {"current_track_id": "source", "artist_name": "First"},
        "bad": False,
        "missing": {"current_track_id": "", "artist_name": "Missing"},
        "": {"current_track_id": "source", "artist_name": "Last"},
    }
    state: dict[str, object] = {"composer_routes": routes}
    other = replace(SOURCE, spotify_id="other", primary_artist_id="other")
    run = new_run("queue", [SOURCE, SOURCE, other], state, clock.now, 10)
    entries = cast(list[dict[str, object]], run["entries"])
    assert [entry["artist_id"] for entry in entries] == ["", "other"]
    assert entries[0]["artist_name"] == "Last" and entries[0]["source"] == asdict(
        SOURCE
    )
    assert entries[0]["status"] == "pending" and entries[0]["plan"] is None
    assert run["run_id"] == "20260928T000000000000Z"
    assert run["created_at"] == "2026-09-28T00:00:01+00:00"
    assert len(clock.reads) == 2
    assert state == {"composer_routes": routes}


def test_snapshot_cap_counts_unique_logical_artists_in_original_order() -> None:
    """The daily cap excludes duplicate artists without consuming later slots."""
    tracks: list[PlaylistTrack] = []
    for index in range(12):
        marker = replace(SOURCE, spotify_id=str(index), primary_artist_id=str(index))
        tracks.extend([marker, marker])
    run = new_run("queue", tracks, {"composer_routes": {}}, SnapshotClock().now, 10)
    entries = cast(list[dict[str, object]], run["entries"])
    expected = []
    for index in range(10):
        expected.append(str(index))
    assert [entry["artist_id"] for entry in entries] == expected


def test_empty_snapshot_still_reads_both_original_timestamps() -> None:
    """An empty queue creates an empty active run without suppressing clock reads."""
    clock = SnapshotClock()
    run = new_run("queue", [], {"composer_routes": {}}, clock.now, 10)
    assert run["entries"] == [] and run["status"] == "active"
    assert len(clock.reads) == 2
