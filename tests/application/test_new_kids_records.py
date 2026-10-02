"""Discovery checkpoints retain decoding, progress mutation and run snapshots."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from typing import cast

import pytest

from spotify_manager.application.new_kids_state import artist_progress
from spotify_manager.application.new_kids_state import logical_artist
from spotify_manager.application.new_kids_state import new_run
from spotify_manager.application.new_kids_state import positive_int
from spotify_manager.application.new_kids_state import release_from_record
from spotify_manager.application.new_kids_state import result_from_plan
from spotify_manager.application.new_kids_state import source_from_record
from spotify_manager.application.new_kids_state import track_from_record
from spotify_manager.application.new_kids_values import NewKidsStateError
from tests.support.discovery_values import release
from tests.support.discovery_values import track
from tests.support.listening_values import playlist_track
from tests.support.listening_values import studio_release


SOURCE = playlist_track("source", studio_release("album", "Album"))
NOW = datetime(2026, 9, 27, tzinfo=UTC)


@dataclass
class Clock:
    """Expose distinct instants so tests can verify the original clock boundaries.

    Args:
        calls: Number of instants already observed.
    """

    calls: int = 0

    def now(self) -> datetime:
        """Observe the next timestamp.

        Returns:
            Original fixed instant plus one microsecond per previous read.
        """
        instant = NOW + timedelta(microseconds=self.calls)
        self.calls += 1
        return instant


@pytest.mark.parametrize(
    "raw,expected",
    [(0, 0), (3, 3), (True, 7), (False, 7), (-1, 7), ("3", 7), (None, 7), (3.5, 7)],
)
def test_progress_counts_keep_nonnegative_integer_validation(
    raw: object, expected: int
) -> None:
    """Booleans and coercible strings retain the existing fallback behavior.

    Args:
        raw: Original decoded count.
        expected: Existing accepted count or supplied fallback.
    """
    assert positive_int(raw, 7) == expected


@pytest.mark.parametrize("raw", [None, [], "invalid"])
def test_nonrecord_catalog_values_keep_existing_errors(raw: object) -> None:
    """Saved catalog boundaries reject non-record values before constructor calls.

    Args:
        raw: Invalid source/release/track representation.
    """
    with pytest.raises(NewKidsStateError, match="source track"):
        source_from_record(raw)
    with pytest.raises(NewKidsStateError, match="invalid release"):
        release_from_record(raw)
    if raw is None:
        assert track_from_record(raw) is None
        return
    with pytest.raises(NewKidsStateError, match="invalid track"):
        track_from_record(raw)


def test_source_decoding_retains_string_coercion_and_unknown_outer_fields() -> None:
    """Unknown source fields remain ignored while release constructors stay strict."""
    raw = asdict(SOURCE)
    raw.update(spotify_id=123, name=None, future=True)
    assert source_from_record(raw) == replace(SOURCE, spotify_id="123", name="None")
    with pytest.raises(NewKidsStateError, match="source track"):
        source_from_record({"release": []})
    del raw["uri"]
    with pytest.raises(KeyError, match="uri"):
        source_from_record(raw)


def test_catalog_constructors_keep_missing_defaults_and_reject_unknown_fields() -> None:
    """Keep original dataclass constructor validation and defaults."""
    raw_track = asdict(track("track"))
    del raw_track["popularity"]
    assert track_from_record(raw_track) == track("track")
    assert release_from_record(asdict(release("album"))) == release("album")
    with pytest.raises(TypeError):
        release_from_record({})
    with pytest.raises(TypeError):
        track_from_record({**raw_track, "unknown": True})


def test_new_artist_progress_is_stored_before_obsolete_keys_are_removed() -> None:
    """Creation uses original source credit facts and exactly one timestamp read."""
    artists: dict[str, object] = {"composer": "invalid old progress"}
    clock = Clock()
    result = artist_progress(
        {"artists": artists}, SOURCE, "composer", "Bach", clock.now
    )
    assert result == {
        "artist_name": "Bach",
        "current_release_id": "album",
        "prior_unliked_streak": None,
        "updated_at": NOW.isoformat(),
    }
    assert artists["composer"] is result and clock.calls == 1


def test_existing_progress_preserves_unknown_fields_without_reading_clock() -> None:
    """Legacy selection fields alone are removed from the accepted mutable record."""
    row: dict[str, object] = {
        "artist_name": "Original",
        "future": 1,
        "selected_release_ids": ["a"],
        "selected_release_identities": ["album"],
        "completed_release_ids": ["a"],
    }
    clock = Clock()
    result = artist_progress(
        {"artists": {"composer": row}}, SOURCE, "composer", "Bach", clock.now
    )
    assert result is row and row == {"artist_name": "Original", "future": 1}
    assert clock.calls == 0


def test_missing_or_invalid_artist_container_keeps_original_error_types() -> None:
    """Outer namespace validation remains distinct from progress initialization."""
    clock = Clock()
    with pytest.raises(KeyError, match="artists"):
        artist_progress({}, SOURCE, "artist", "Artist", clock.now)
    with pytest.raises(AssertionError):
        artist_progress({"artists": []}, SOURCE, "artist", "Artist", clock.now)
    assert clock.calls == 0


@pytest.mark.parametrize(
    "routes",
    [
        None,
        [],
        "invalid",
        {},
        {"invalid": None},
        {"other": {"current_track_id": "different", "artist_name": "Other"}},
        {"blank": {"current_track_id": "source", "artist_name": " "}},
    ],
)
def test_unusable_routes_keep_original_primary_credit(routes: object) -> None:
    """Missing, malformed and unmatched routes never override the marker credit.

    Args:
        routes: Existing route container or row to ignore.
    """
    assert logical_artist({"composer_routes": routes}, SOURCE) == ("artist", "Artist")


def test_first_matching_route_wins_with_existing_string_and_whitespace_coercions() -> (
    None
):
    """Logical artist resolution preserves insertion order and ID conversion."""
    routes = {
        7: {"current_track_id": "source", "artist_name": " Bach "},
        "other": {"current_track_id": "source", "artist_name": "Other"},
    }
    assert logical_artist({"composer_routes": routes}, SOURCE) == ("7", "Bach")


def test_run_snapshot_deduplicates_logical_artists_before_reading_timestamps() -> None:
    """Deduplicate logical artists while retaining source performer credits."""
    second = replace(SOURCE, spotify_id="second")
    third = replace(
        SOURCE,
        spotify_id="third",
        primary_artist_id="other",
        primary_artist_name="Other",
    )
    state: dict[str, object] = {
        "composer_routes": {
            "composer": {"current_track_id": "source", "artist_name": "Bach"}
        }
    }
    clock = Clock()
    result = new_run("new", [SOURCE, SOURCE, second, third], state, clock.now)
    entries = cast(list[dict[str, object]], result["entries"])
    assert [entry["artist_id"] for entry in entries] == ["composer", "artist", "other"]
    assert entries[0] == {
        "source": asdict(SOURCE),
        "artist_id": "composer",
        "artist_name": "Bach",
        "status": "pending",
        "plan": None,
    }
    assert result["run_id"] == NOW.strftime("%Y%m%dT%H%M%S%fZ")
    assert result["started_at"] == (NOW + timedelta(microseconds=1)).isoformat()
    assert clock.calls == 2 and result["status"] == "active"


def test_minimal_result_plan_retains_unknown_action_and_default_fields() -> None:
    """Retain tolerant actions and missing optional metadata in result translation."""
    result = result_from_plan(SOURCE, {"result_action": "future"}, True)
    assert str(result.action) == "future" and result.dry_run
    assert result.artist == "Artist" and result.consecutive_unliked == 0
    assert result.target_track is None
    assert result.album_decision is None
    assert result.release_number is None
    assert result.qualification_reasons == ()
    with pytest.raises(KeyError, match="result_action"):
        result_from_plan(SOURCE, {}, False)


def test_rich_result_plan_keeps_original_optional_coercions() -> None:
    """Reject boolean counts while retaining original name and reason coercions."""
    plan: dict[str, object] = {
        "result_action": "advance",
        "target": asdict(track("next")),
        "target_release": asdict(release("other")),
        "current_liked": "yes",
        "consecutive_unliked": 2,
        "release_number": 3,
        "assessment": {"reasons": [17, None]},
        "evaluation": {"liked_tracks": True, "total_tracks": 8, "decision": "keep"},
        "composer_playlist_name": "Works",
        "composer_position": 4,
        "composer_limit": 40,
    }
    result = result_from_plan(SOURCE, plan, False, artist_name="Bach")
    assert (result.artist, result.target_track, result.target_release) == (
        "Bach",
        "next",
        "other",
    )
    assert result.current_liked and result.release_number == 3
    assert result.qualification_reasons == ("17", "None")
    assert (
        result.album_liked_tracks,
        result.album_total_tracks,
        result.album_decision,
    ) == (0, 8, "keep")
    assert (
        result.composer_playlist,
        result.composer_position,
        result.composer_limit,
    ) == ("Works", 4, 40)


@pytest.mark.parametrize("reasons", [None, "a string", {"not": "a list"}])
def test_result_ignores_nonsequence_reasons_and_empty_decision(reasons: object) -> None:
    """Optional result metadata keeps its existing container and truthiness rules.

    Args:
        reasons: Invalid reasons container to ignore during presentation translation.
    """
    result = result_from_plan(
        SOURCE,
        {
            "result_action": "skip",
            "assessment": {"reasons": reasons},
            "evaluation": {},
            "composer_position": 0,
            "composer_limit": 0,
        },
        False,
    )
    assert result.qualification_reasons == () and result.album_decision is None
    assert result.album_liked_tracks == result.album_total_tracks == 0
    assert result.composer_position is result.composer_limit is None
