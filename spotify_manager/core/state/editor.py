"""Backend-owned presentation and safety rules for manual state editing."""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from typing import Any

from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.core.state.models import canonical_json


StateEditorRule = dict[str, Any]
StateEditorNamespace = dict[str, Any]


def _readonly(path: str) -> StateEditorRule:
    return {"path": path, "read_only": True}


def _select(path: str, *options: str) -> StateEditorRule:
    return {"path": path, "control": "select", "options": list(options)}


STATE_EDITOR_SCHEMA: dict[str, Any] = {
    "document": {
        "label": "Entire state",
        "rules": [
            _readonly("/schema_version"),
            _readonly("/created_at"),
            _readonly("/updated_at"),
            _readonly("/namespaces/*/updated_at"),
        ],
    },
    "namespaces": {
        "discography": {
            "label": "Discographies",
            "rules": [
                _readonly("/version"),
                _select("/next_queue", "newfoundland", "requeue", "memory_lane"),
            ],
        },
        "genre_reveal": {
            "label": "Genre Reveal",
            "rules": [_readonly("/version"), _readonly("/updated_at")],
        },
        "new_kids": {
            "label": "New Kids on the Block",
            "rules": [
                _readonly("/version"),
                _readonly("/active_run"),
                _readonly("/queue_2_active_run"),
            ],
        },
        "new_wine": {
            "label": "New Wine",
            "rules": [_readonly("/version"), _readonly("/active_run")],
        },
        "palace_of_memory": {
            "label": "Palace of Memory",
            "rules": [
                _readonly("/updated_at"),
                _readonly("/last_alphabetical_album_id"),
                _readonly("/last_alphabetical_artist"),
                _readonly("/last_alphabetical_album"),
            ],
        },
        "queue": {
            "label": "The Queue",
            "rules": [_readonly("/version"), _readonly("/active_flush")],
        },
        "queue_3": {
            "label": "The Queue 3",
            "rules": [_readonly("/version"), _readonly("/active_run")],
        },
        "recover_removed_albums": {
            "label": "Removed Album Recovery",
            "rules": [_readonly("/version")],
        },
        "release_check": {
            "label": "New Release Check",
            "rules": [
                _readonly("/version"),
                _readonly("/updated_at"),
                _readonly("/active_run"),
            ],
        },
        "review_album_limits": {
            "label": "Album Limit Review",
            "rules": [_select("/*/decision", "keep")],
        },
        "review_artists": {
            "label": "Artist Review",
            "rules": [_readonly("/version")],
        },
        "slow_listening": {
            "label": "Slow Listening",
            "rules": [_readonly("/version"), _readonly("/active_run")],
        },
    },
}


def state_editor_schema() -> dict[str, Any]:
    """Return a detached schema suitable for an API response."""
    return deepcopy(STATE_EDITOR_SCHEMA)


def namespace_editor_schema(name: str) -> StateEditorNamespace | None:
    """Return one namespace's editor schema when it is registered."""
    schema = STATE_EDITOR_SCHEMA["namespaces"].get(name)
    return deepcopy(schema) if schema is not None else None


def _path_segments(path: str) -> tuple[str, ...]:
    if not path.startswith("/"):
        raise StateDocumentError(f"State editor path must begin with '/': {path}")
    return tuple(
        segment.replace("~1", "/").replace("~0", "~")
        for segment in path[1:].split("/")
        if segment
    )


def _matching_values(
    value: object,
    segments: tuple[str, ...],
    resolved: tuple[str, ...] = (),
) -> Iterator[tuple[tuple[str, ...], object]]:
    if not segments:
        yield resolved, value
        return
    segment, remaining = segments[0], segments[1:]
    if segment == "*":
        if isinstance(value, dict):
            for key, child in value.items():
                yield from _matching_values(child, remaining, (*resolved, str(key)))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from _matching_values(child, remaining, (*resolved, str(index)))
        return
    if isinstance(value, dict) and segment in value:
        yield from _matching_values(value[segment], remaining, (*resolved, segment))
    elif isinstance(value, list) and segment.isdigit():
        index = int(segment)
        if 0 <= index < len(value):
            yield from _matching_values(value[index], remaining, (*resolved, segment))


def _values_by_path(value: object, path: str) -> dict[str, object]:
    return {
        "/".join(resolved): matched
        for resolved, matched in _matching_values(value, _path_segments(path))
    }


def validate_namespace_editor_change(
    name: str,
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> None:
    """Enforce guided-editor constraints before routine validation."""
    schema = namespace_editor_schema(name)
    if schema is None:
        raise StateDocumentError(f"Unknown state namespace: {name}")
    for rule in schema["rules"]:
        path = str(rule["path"])
        candidate_values = _values_by_path(candidate, path)
        if rule.get("read_only"):
            current_values = _values_by_path(current, path)
            if canonical_json(current_values) != canonical_json(candidate_values):
                raise StateDocumentError(f"State field {path} is read-only.")
        options = rule.get("options")
        if options is not None:
            for value in candidate_values.values():
                if value not in options:
                    choices = ", ".join(repr(option) for option in options)
                    raise StateDocumentError(
                        f"State field {path} must be one of: {choices}."
                    )
