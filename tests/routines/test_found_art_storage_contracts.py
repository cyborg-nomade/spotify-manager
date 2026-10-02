"""Original recommendation cache tolerance, JSON bytes and audit diagnostics."""

import json
import math
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import cast
from unittest.mock import Mock

import pytest

from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import found_art
from tests.routines.test_found_art import candidate
from tests.routines.test_found_art import seed


WEEK = date(2026, 7, 17)
STAMP = "2026-07-23T12:00:00+00:00"
FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/found_art_storage.json"
)


def _summary() -> found_art.FoundArtSummary:
    match = blast.SpotifyTrackMatch(
        "id", "uri", "Café", ("Beyoncé",), "Album", 3, 0.9, 0.1, None, True
    )
    recommendation = candidate("Beyoncé", "Café", 1.25)
    return found_art.FoundArtSummary(
        datetime(2026, 7, 23, tzinfo=UTC),
        WEEK,
        "destination",
        1,
        1,
        2,
        3,
        1,
        2,
        5,
        6,
        False,
        (seed("Seed", "Song"),),
        (
            found_art.FoundArtResult(recommendation, match, "added"),
            found_art.FoundArtResult(
                candidate("Other", "Missing", 0.1), None, "no Spotify match"
            ),
        ),
    )


def _cache_payload() -> dict[str, object]:
    return {
        "version": 1,
        "entries": {
            "artist\0song": {
                "artist": "Beyoncé",
                "track": "Café",
                "fetched_at": STAMP,
                "tracks": [{"artist": "Other", "track": "Song", "match": 0.5}],
            }
        },
    }


def _fixture() -> dict[str, object]:
    return cast(dict[str, object], json.loads(FIXTURE.read_text()))


def test_cache_and_audit_bytes_match_original_snapshots(tmp_path: Path) -> None:
    """Preserve Unicode, indentation, field order, omissions and append newlines.

    Args:
        tmp_path: Isolated cache and audit destinations.
    """
    cache, audit = tmp_path / "cache.json", tmp_path / "audit.jsonl"
    found_art._save_similar_cache(_cache_payload(), cache)
    found_art.append_found_art_log(_summary(), audit)
    found_art.append_found_art_log(_summary(), audit)
    assert cache.read_text() == _fixture()["cache_text"]
    assert audit.read_text() == cast(str, _fixture()["audit_text"]) * 2
    assert not cache.with_suffix(".json.tmp").exists()
    assert found_art._load_similar_cache(cache) == _cache_payload()


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"version": 2, "entries": {}}, {"version": 1, "entries": []}],
)
def test_cache_schema_rejection_preserves_error_without_cause(
    tmp_path: Path, payload: object
) -> None:
    """Reject original invalid shapes while keeping schema errors distinct from IO.

    Args:
        tmp_path: Isolated cache destination.
        payload: Original JSON schema boundary case.
    """
    path = tmp_path / "cache.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(
        found_art.FoundArtStateError, match="cache is invalid"
    ) as raised:
        found_art._load_similar_cache(path)
    assert raised.value.__cause__ is None


def test_cache_missing_file_and_numeric_version_equality_are_preserved(
    tmp_path: Path,
) -> None:
    """Keep the empty default and original permissive equality for version one.

    Args:
        tmp_path: Isolated cache destination.
    """
    path = tmp_path / "cache.json"
    assert found_art._load_similar_cache(path) == {"version": 1, "entries": {}}
    payload = {"version": True, "entries": {}, "extra": [1]}
    path.write_text(json.dumps(payload))
    assert found_art._load_similar_cache(path) == payload


@pytest.mark.parametrize("failure", ["mkdir", "write_text", "replace"])
def test_cache_replacement_failure_retains_prior_bytes_and_original_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """A failed checkpoint never replaces the previous valid destination.

    Args:
        tmp_path: Isolated cache destination.
        monkeypatch: Scoped original filesystem failure.
        failure: Original accepted-write boundary to fail.
    """
    path = tmp_path / "cache.json"
    path.write_text("prior")
    error = PermissionError(failure)
    monkeypatch.setattr(Path, failure, Mock(side_effect=error))
    with pytest.raises(found_art.FoundArtStateError, match="Could not save") as raised:
        found_art._save_similar_cache(_cache_payload(), path)
    assert raised.value.__cause__ is error
    assert path.read_text() == "prior"
    assert path.with_suffix(".json.tmp").exists() is (failure == "replace")


def test_cache_json_encoding_failure_is_not_reclassified(tmp_path: Path) -> None:
    """Retain original TypeError propagation outside narrowed filesystem handling.

    Args:
        tmp_path: Isolated cache destination.
    """
    with pytest.raises(TypeError):
        found_art._save_similar_cache({"value": object()}, tmp_path / "cache.json")


@pytest.mark.parametrize(
    "entry",
    [
        None,
        [],
        {},
        {"fetched_at": "bad", "tracks": []},
        {"fetched_at": STAMP, "tracks": ()},
        {"fetched_at": STAMP, "tracks": [{"artist": "A"}]},
        {"fetched_at": STAMP, "tracks": [{"artist": "A", "track": "T", "match": None}]},
        {
            "fetched_at": STAMP,
            "tracks": [{"artist": "A", "track": "T", "match": "bad"}],
        },
        {"fetched_at": "2026-07-24T12:00:00+00:00"},
    ],
)
def test_invalid_or_stale_neighborhood_is_a_complete_cache_miss(entry: object) -> None:
    """Invalid rows reject the whole observation while stale weeks skip row decoding.

    Args:
        entry: Original tolerant decoder boundary case.
    """
    assert found_art._cached_similar_tracks(entry, week_start=WEEK) is None


@pytest.mark.parametrize(
    "stamp", [STAMP, "2026-07-23T12:00:00", "2026-07-16T22:00:00+00:00"]
)
def test_neighborhood_ignores_nonobjects_and_preserves_string_coercion(
    stamp: str,
) -> None:
    """Decode UTC-naive and Berlin-Friday dates with permissive original values.

    Args:
        stamp: Original valid effective-week timestamp representation.
    """
    entry = {
        "fetched_at": stamp,
        "tracks": [None, 1, {"artist": None, "track": 123, "match": "0.5"}],
    }
    assert found_art._cached_similar_tracks(entry, week_start=WEEK) == (
        found_art.LastFmSimilarTrack("None", "123", 0.5),
    )


def test_neighborhood_preserves_nonfinite_match_and_uncaught_numeric_overflow() -> None:
    """Do not tighten original float coercion during a behavior-preserving move."""
    entry = {
        "fetched_at": STAMP,
        "tracks": [{"artist": "A", "track": "T", "match": "NaN"}],
    }
    tracks = found_art._cached_similar_tracks(entry, week_start=WEEK)
    assert tracks is not None and math.isnan(tracks[0].match)
    entry["tracks"] = [{"artist": "A", "track": "T", "match": 10**1000}]
    with pytest.raises(OverflowError):
        found_art._cached_similar_tracks(entry, week_start=WEEK)


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        {},
        {"results": None},
        {"results": [{"action": "added", "candidate": None}]},
        {"results": [{"action": "added", "candidate": {"artist": "A"}}]},
    ],
)
def test_invalid_audit_record_reports_original_physical_line(
    tmp_path: Path, record: object
) -> None:
    """Blank physical lines still count toward the original chained diagnostic.

    Args:
        tmp_path: Isolated audit destination.
        record: Original invalid parsed record boundary.
    """
    path = tmp_path / "audit.jsonl"
    path.write_text(
        "\n" + json.dumps({"results": []}) + "\n" + json.dumps(record) + "\n"
    )
    with pytest.raises(found_art.FoundArtStateError, match="at line 3") as raised:
        found_art.previously_added_track_keys(path)
    assert isinstance(raised.value.__cause__, (KeyError, ValueError))


def test_audit_ignores_nonadded_rows_but_preserves_invalid_normalized_added_keys(
    tmp_path: Path,
) -> None:
    """Keep preview/unknown actions excluded and original added-key coercion tolerance.

    Args:
        tmp_path: Isolated audit destination.
    """
    path = tmp_path / "audit.jsonl"
    assert found_art.previously_added_track_keys(path) == set()
    records = {
        "results": [
            1,
            {},
            {"action": "would add"},
            {"action": "added", "candidate": {"artist": "", "track": ""}},
            {"action": "added", "candidate": {"artist": None, "track": 123}},
        ]
    }
    path.write_text(json.dumps(records) + "\n")
    assert found_art.previously_added_track_keys(path) == {("", ""), ("none", "123")}


def test_audit_open_failure_omits_line_detail(tmp_path: Path) -> None:
    """Preserve chained filesystem failures before any physical line is read.

    Args:
        tmp_path: Existing directory used as the invalid audit source.
    """
    with pytest.raises(
        found_art.FoundArtStateError, match="audit log is invalid:"
    ) as raised:
        found_art.previously_added_track_keys(tmp_path)
    assert isinstance(raised.value.__cause__, OSError)


class InterruptedAudit:
    """Yield original physical lines before a simulated read interruption."""

    def __init__(self) -> None:
        """Initialize the original accepted-line counter."""
        self.lines = 0

    def __enter__(self) -> InterruptedAudit:
        """Enter the original log read boundary.

        Returns:
            This interrupted reader.
        """
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the original read boundary without suppressing its exception.

        Args:
            kind: Original exception type.
            error: Original exception instance.
            traceback: Original traceback.
        """

    def __iter__(self) -> InterruptedAudit:
        """Begin ordered physical-line observation.

        Returns:
            This interrupted reader.
        """
        return self

    def __next__(self) -> str:
        """Read two original physical lines before interruption.

        Returns:
            One original line.

        Raises:
            OSError: The next physical line cannot be read.
        """
        self.lines += 1
        if self.lines == 3:
            raise OSError("read interrupted")
        return "\n" if self.lines == 1 else '{"results": []}\n'


def test_audit_read_failure_reports_last_accepted_physical_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain original line-two diagnostics when reading the next line fails.

    Args:
        tmp_path: Existing isolated log path.
        monkeypatch: Scoped interrupted reader.
    """
    path = tmp_path / "audit.jsonl"
    path.write_text("unused")
    monkeypatch.setattr(Path, "open", Mock(return_value=InterruptedAudit()))
    with pytest.raises(found_art.FoundArtStateError, match="at line 2") as raised:
        found_art.previously_added_track_keys(path)
    assert isinstance(raised.value.__cause__, OSError)
