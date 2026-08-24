import math

import pytest

from spotify_manager.core.state import StateDocumentError
from spotify_manager.core.state.models import canonical_json
from spotify_manager.core.state.models import new_document
from spotify_manager.core.state.models import validate_document
from spotify_manager.core.state.models import with_namespace


def valid_document():
    document = new_document()
    document["namespaces"]["queue"] = {
        "updated_at": document["updated_at"],
        "value": {},
    }
    return document


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda _document: [], "JSON object"),
        (lambda document: document.update(schema_version=99), "schema_version"),
        (lambda document: document.update(namespaces=[]), "namespaces"),
        (
            lambda document: document.update(
                namespaces={"": document["namespaces"]["queue"]}
            ),
            "non-empty strings",
        ),
        (
            lambda document: document.update(namespaces={"queue": []}),
            "must be an object",
        ),
        (
            lambda document: document["namespaces"]["queue"].update(updated_at=1),
            "updated_at string",
        ),
        (
            lambda document: document["namespaces"]["queue"].update(value=[]),
            "value must be a JSON object",
        ),
        (lambda document: document.update(created_at=1), "created_at"),
        (
            lambda document: document["namespaces"]["queue"]["value"].update(
                unsupported={1, 2}
            ),
            "valid JSON data",
        ),
    ],
)
def test_document_validation_rejects_malformed_state(mutate, message):
    document = valid_document()
    candidate = mutate(document)

    with pytest.raises(StateDocumentError, match=message):
        validate_document(candidate if candidate is not None else document)


def test_canonical_json_rejects_non_finite_numbers():
    with pytest.raises(StateDocumentError, match="valid JSON data"):
        canonical_json({"value": math.nan})


def test_with_namespace_validates_name_and_value():
    with pytest.raises(StateDocumentError, match="cannot be empty"):
        with_namespace(new_document(), "", {})
    with pytest.raises(StateDocumentError, match="must be a JSON object"):
        with_namespace(new_document(), "queue", [])  # type: ignore[arg-type]
