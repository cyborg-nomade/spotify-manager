"""Validate the versioned durable Something Old choice-history namespace."""

from dataclasses import fields
from typing import cast

from pydantic import TypeAdapter
from pydantic import ValidationError

from spotify_manager.core.state.models import StateDocumentError
from spotify_manager.domain.something_old_history import ArtistChoice
from spotify_manager.domain.something_old_history import ChoiceLedger
from spotify_manager.domain.something_old_history import choice_identity


_LEDGER = TypeAdapter(ChoiceLedger)
_CHOICE_FIELDS = {item.name for item in fields(ArtistChoice)}


def validate_choice(choice: ArtistChoice) -> None:
    """Reject incomplete identities, dates or selections instead of counting them.

    Args:
        choice: Parsed candidate evidence.

    Raises:
        StateDocumentError: Required evidence is missing or the date is naive.
    """
    labels = (
        choice.artist_id,
        choice.artist_name,
        choice.lastfm_artist,
        choice.playlist_id,
    )
    if any(not label.strip() for label in labels):
        raise StateDocumentError("Something Old choice history has an empty identity.")
    if choice.chosen_at.tzinfo is None or not choice.track_ids:
        raise StateDocumentError(
            "Something Old choice history has incomplete evidence."
        )
    if any(not identity.strip() for identity in choice.track_ids):
        raise StateDocumentError(
            "Something Old choice history has invalid track identities."
        )


def _check_raw(raw: object) -> None:
    if not isinstance(raw, dict) or set(raw) != {"version", "choices", "pending"}:
        raise StateDocumentError("Something Old choice history has an invalid format.")
    if type(raw.get("version")) is not int or raw["version"] != 1:
        raise StateDocumentError("Something Old choice history version is unsupported.")
    for name in ("choices", "pending"):
        _check_records(raw[name])


def _check_records(raw: object) -> None:
    if not isinstance(raw, dict):
        raise StateDocumentError(
            "Something Old choice history records must be objects."
        )
    for record in raw.values():
        if not isinstance(record, dict) or set(record) - _CHOICE_FIELDS:
            raise StateDocumentError(
                "Something Old choice history has unknown record fields."
            )


class SomethingOldChoiceDefinition:
    """Own the durable completed-selection and unconfirmed-intent format."""

    def default(self) -> dict[str, object]:
        """Construct an empty independent history namespace.

        Returns:
            Version 1 with no completed or pending events.
        """
        return self.encode(ChoiceLedger())

    def decode(self, raw: object) -> ChoiceLedger:
        """Parse and validate identities, event keys and pending destinations.

        Args:
            raw: Untrusted persisted JSON object.

        Returns:
            Typed evidence retaining every valid event.

        Raises:
            StateDocumentError: The version, shape, identities or evidence are invalid.
        """
        _check_raw(raw)
        try:
            ledger = _LEDGER.validate_python(raw)
        except ValidationError as exc:
            raise StateDocumentError(
                "Something Old choice history is invalid."
            ) from exc
        for identity, choice in ledger.choices.items():
            validate_choice(choice)
            if identity != choice_identity(choice):
                raise StateDocumentError(
                    "Something Old choice history event identity differs."
                )
        for playlist, choice in ledger.pending.items():
            validate_choice(choice)
            if playlist != choice.playlist_id:
                raise StateDocumentError(
                    "Something Old choice history destination differs."
                )
        return ledger

    def encode(self, ledger: ChoiceLedger) -> dict[str, object]:
        """Serialize typed evidence to portable JSON values.

        Args:
            ledger: Complete current evidence.

        Returns:
            Versioned JSON object, including all completed and pending records.
        """
        return cast(dict[str, object], _LEDGER.dump_python(ledger, mode="json"))

    def validate(self, raw: object) -> dict[str, object]:
        """Validate a namespace at the existing shared-state boundary.

        Args:
            raw: Untrusted namespace value.

        Returns:
            Complete validated JSON value.

        Raises:
            StateDocumentError: The namespace is unusable.
        """
        return self.encode(self.decode(raw))
