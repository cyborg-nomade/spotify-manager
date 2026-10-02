"""Verify original shallow annual validation and retained unknown records."""

import pytest

from spotify_manager.application.new_year_values import NewYearError
from spotify_manager.infrastructure.new_year_state import validate_state


@pytest.mark.parametrize(
    "raw,message",
    [
        (None, "Invalid New Year's Routines state"),
        ({}, "Invalid New Year's Routines state"),
        ({"years": []}, "Invalid New Year's Routines state"),
        ({"years": {"unknown": {}}}, "Invalid retrospective year state"),
        ({"years": {"2025": []}}, "Invalid retrospective year state"),
        ({"years": {"2025": {"completed": None}}}, "Invalid retrospective checkpoints"),
        ({"years": {"2025": {"plan": []}}}, "Invalid retrospective checkpoints"),
    ],
)
def test_annual_state_rejects_only_original_invalid_containers(
    raw: object, message: str
) -> None:
    """Retain original root, year and checkpoint shape errors.

    Args:
        raw: Original invalid untrusted record.
        message: Original error text.
    """
    with pytest.raises(NewYearError, match=message):
        validate_state(raw)


def test_annual_state_retains_digit_keys_and_unknown_fields() -> None:
    """Retain Unicode/integer digit keys, arbitrary completion members and raw plans."""
    raw: dict[str, object] = {
        "extra": "retained",
        "years": {
            2025: {},
            "٢٠٢٥": {
                "completed": [1, False],
                "plan": {"anything": "unvalidated"},
                "done": "truthy",
                "extra": [1],
            },
        },
    }
    assert validate_state(raw) is raw
