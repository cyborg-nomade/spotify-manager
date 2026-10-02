"""Preserve original shallow annual validation without narrowing resumed records."""

from typing import cast

from spotify_manager.application.new_year_values import NewYearError


def validate_state(raw: object) -> dict[str, object]:
    """Validate original namespace containers and digit-keyed annual checkpoints.

    Args:
        raw: Original complete untrusted annual namespace.

    Returns:
        Original mutable record, including every unknown field.

    Raises:
        NewYearError: An original root, year or checkpoint container is invalid.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("years"), dict):
        raise NewYearError("Invalid New Year's Routines state.")
    for year, run in raw["years"].items():
        _validate_run(year, run)
    return cast(dict[str, object], raw)


def _validate_run(year: object, run: object) -> None:
    if not str(year).isdigit() or not isinstance(run, dict):
        raise NewYearError("Invalid retrospective year state.")
    if not isinstance(run.get("completed", []), list) or not isinstance(
        run.get("plan", {}), dict
    ):
        raise NewYearError("Invalid retrospective checkpoints.")
