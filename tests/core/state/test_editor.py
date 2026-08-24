import pytest

from spotify_manager.core.state import StateDocumentError
from spotify_manager.core.state.editor import _matching_values
from spotify_manager.core.state.editor import _path_segments
from spotify_manager.core.state.editor import namespace_editor_schema
from spotify_manager.core.state.editor import state_editor_schema
from spotify_manager.core.state.editor import validate_namespace_editor_change


def test_schema_is_detached_and_describes_constrained_fields():
    schema = state_editor_schema()
    schema["namespaces"]["discography"]["label"] = "changed"

    discography = namespace_editor_schema("discography")

    assert discography is not None
    assert discography["label"] == "Discographies"
    assert discography["rules"][1] == {
        "path": "/next_queue",
        "control": "select",
        "options": ["newfoundland", "requeue", "memory_lane"],
    }
    assert namespace_editor_schema("missing") is None


def test_namespace_constraints_allow_valid_guided_changes():
    current = {"version": 1, "next_queue": "requeue"}

    validate_namespace_editor_change(
        "discography",
        current,
        {"version": 1, "next_queue": "memory_lane"},
    )


@pytest.mark.parametrize(
    ("candidate", "message"),
    [
        ({"version": 2, "next_queue": "requeue"}, "read-only"),
        ({"version": 1, "next_queue": "unknown"}, "must be one of"),
    ],
)
def test_namespace_constraints_reject_unsafe_changes(candidate, message):
    with pytest.raises(StateDocumentError, match=message):
        validate_namespace_editor_change(
            "discography",
            {"version": 1, "next_queue": "requeue"},
            candidate,
        )


def test_wildcard_options_validate_dynamic_entries():
    current = {"album-1": {"decision": "keep"}}
    validate_namespace_editor_change("review_album_limits", current, current)

    with pytest.raises(StateDocumentError, match="must be one of"):
        validate_namespace_editor_change(
            "review_album_limits",
            current,
            {"album-1": {"decision": "remove"}},
        )


def test_unknown_namespace_and_invalid_paths_are_rejected():
    with pytest.raises(StateDocumentError, match="Unknown state namespace"):
        validate_namespace_editor_change("missing", {}, {})
    with pytest.raises(StateDocumentError, match="must begin"):
        _path_segments("not-a-pointer")


def test_path_matching_supports_lists_and_numeric_indexes():
    value = {"rows": [{"status": "first"}, {"status": "second"}]}

    wildcard = dict(_matching_values(value, ("rows", "*", "status")))
    indexed = dict(_matching_values(value, ("rows", "1", "status")))
    missing = list(_matching_values(value, ("rows", "8", "status")))

    assert wildcard == {
        ("rows", "0", "status"): "first",
        ("rows", "1", "status"): "second",
    }
    assert indexed == {("rows", "1", "status"): "second"}
    assert missing == []
