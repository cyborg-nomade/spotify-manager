"""Verify tolerant library rows, original staging failure rules and undo boundaries."""

import json
from functools import partial
from pathlib import Path

import pytest

from spotify_manager.domain.library_analysis_values import IncompleteLiveResourceError
from spotify_manager.domain.library_analysis_values import LibrarySyncError
from spotify_manager.infrastructure import library_analysis_files as files
from spotify_manager.models.your_library import YourLibraryAlbum
from spotify_manager.models.your_library import YourLibraryArtist
from tests.application.library_analysis_memory import AnalysisMemory
from tests.application.library_analysis_memory import memory_session


@pytest.mark.parametrize(
    "raw",
    [
        None,
        {},
        {"track": None},
        {"track": {"id": "a", "name": "Track", "artists": [], "album": {}}},
    ],
)
def test_unusable_saved_tracks_are_ignored(raw: object) -> None:
    """Retain original required primary-credit and album-name validation.

    Args:
        raw: Original unusable saved-track boundary row.
    """
    assert files.track_from_saved_item(raw) is None


def test_saved_track_uses_original_primary_credit_and_fallback_uri() -> None:
    """Retain original string conversion and first-credit authority."""
    raw = {
        "track": {
            "id": 7,
            "name": 8,
            "artists": [{"name": 9}, {"name": "Other"}],
            "album": {"name": 10},
        }
    }
    model = files.track_from_saved_item(raw)
    assert model is not None
    assert (model.artist, model.album, model.track, model.uri) == (
        "9",
        "10",
        "8",
        "spotify:track:7",
    )


@pytest.mark.parametrize("raw", [None, {}, {"id": "a", "name": ""}])
def test_unusable_artist_rows_are_ignored(raw: object) -> None:
    """Retain original artist id/name truthiness checks.

    Args:
        raw: Original unusable artist boundary row.
    """
    assert files.artist_from_api_item(raw) is None


def test_artist_row_retains_original_fallback_identity() -> None:
    """Retain original raw id/name string conversion and fallback URI."""
    assert files.artist_from_api_item({"id": 7, "name": 8}) == YourLibraryArtist(
        name="8", uri="spotify:artist:7"
    )


@pytest.mark.parametrize("raw", [None, {}, {"items": None}])
def test_malformed_offset_page_has_original_error(raw: object) -> None:
    """Retain original offset page validation and resource-specific message.

    Args:
        raw: Original malformed page envelope.
    """
    with pytest.raises(IncompleteLiveResourceError, match="invalid tracks page"):
        files.page_items(raw, "tracks")


@pytest.mark.parametrize(
    "raw", [None, {}, {"artists": None}, {"artists": {"items": None}}]
)
def test_malformed_artist_page_has_original_error(raw: object) -> None:
    """Retain original artist page and item-list shape boundaries.

    Args:
        raw: Original malformed cursor page envelope.
    """
    with pytest.raises(IncompleteLiveResourceError, match="invalid followed-artists"):
        files.followed_artist_page_items(raw)


@pytest.mark.parametrize("payload", ["broken JSON", "[]", '"text"'])
def test_export_read_retains_original_error_translation(
    tmp_path: Path, payload: str
) -> None:
    """Retain original read-versus-model validation error causes.

    Args:
        tmp_path: Independent original output family.
        payload: Original invalid persisted export.
    """
    session = memory_session(AnalysisMemory(), tmp_path)
    session.paths.your_library.write_text(payload)
    with pytest.raises(LibrarySyncError) as failure:
        files.load_your_library(session.paths, read=files.load_json)
    assert failure.value.__cause__ is not None


def test_json_and_export_missing_file_semantics_are_distinct(tmp_path: Path) -> None:
    """Keep caller defaults for absent JSON and errors for absent export authority.

    Args:
        tmp_path: Independent original output family.
    """
    session = memory_session(AnalysisMemory(), tmp_path)
    missing = session.paths.your_library
    assert files.load_json(missing, default="default") == "default"
    with pytest.raises(LibrarySyncError, match="export not found"):
        files.load_your_library(session.paths, read=files.load_json)
    with pytest.raises(LibrarySyncError, match="export not found"):
        files.export_fingerprint(missing)


def test_model_array_rejects_nonlist_json_and_propagates_model_validation(
    tmp_path: Path,
) -> None:
    """Keep original missing-list defaults and native model-validation failures.

    Args:
        tmp_path: Independent original model-array location.
    """
    target = tmp_path / "models.json"
    reader = partial(
        files.load_model_list, model=YourLibraryAlbum, read=files.load_json
    )
    assert reader(target) == []
    target.write_text("{}")
    with pytest.raises(LibrarySyncError, match="Expected a JSON list"):
        reader(target)
    target.write_text("[{}]")
    with pytest.raises(ValueError):
        reader(target)


@pytest.mark.parametrize("invalid", ["broken JSON", "{}", ""])
def test_torn_final_staging_line_is_ignored_but_earlier_corruption_fails(
    tmp_path: Path, invalid: str
) -> None:
    """Retain original final-line recovery without skipping earlier invalid records.

    Args:
        tmp_path: Independent original staging location.
        invalid: Original torn or invalid-model staging line.
    """
    target = tmp_path / "artists.jsonl"
    valid = YourLibraryArtist(name="Name", uri="spotify:artist:a").model_dump_json()
    target.write_text(f"{valid}\n{invalid}\n")
    assert files.load_models_jsonl(target, YourLibraryArtist) == [
        YourLibraryArtist(name="Name", uri="spotify:artist:a")
    ]
    target.write_text(f"{invalid}\n{valid}\n")
    with pytest.raises(LibrarySyncError, match="Invalid staging data") as failure:
        files.load_models_jsonl(target, YourLibraryArtist)
    assert failure.value.__cause__ is None


def test_loading_staging_missing_file_is_empty(tmp_path: Path) -> None:
    """Retain original missing-staging default.

    Args:
        tmp_path: Independent absent staging location.
    """
    assert files.load_models_jsonl(tmp_path / "missing.jsonl", YourLibraryArtist) == []


def test_load_json_read_error_keeps_original_cause(tmp_path: Path) -> None:
    """Retain original operating-system read-error translation.

    Args:
        tmp_path: Directory that cannot be read as an original JSON file.
    """
    with pytest.raises(LibrarySyncError, match="Could not read valid JSON") as failure:
        files.load_json(tmp_path)
    assert isinstance(failure.value.__cause__, OSError)


def _clock() -> str:
    return "original-clock"


def test_audit_retains_unknown_details_named_like_the_clock_dependency(
    tmp_path: Path,
) -> None:
    """Keep arbitrary original audit keys without colliding with injected dependencies.

    Args:
        tmp_path: Independent original audit location.
    """
    session = memory_session(AnalysisMemory(), tmp_path)
    files.append_event(
        _clock,
        session.paths,
        "run",
        "name",
        now="original detail",
        timestamp="override",
    )
    event = json.loads(session.paths.event_log.read_text())
    assert event == {
        "timestamp": "override",
        "run_id": "run",
        "mode": "mirrors",
        "event": "name",
        "now": "original detail",
    }
