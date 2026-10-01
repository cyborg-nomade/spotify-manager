"""Read immutable original Queue policy scenarios from trusted offline JSON."""

import json
from pathlib import Path
from typing import cast


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/queue_history_seeds.json"
)
type PolicyCase = dict[str, object]


def cases() -> list[tuple[str, PolicyCase]]:
    """Read original history and weekly-seed observations.

    Returns:
        Named original inputs and frozen outcomes.
    """
    payload = cast(dict[str, PolicyCase], json.loads(FIXTURE.read_text()))
    return list(payload.items())


def records(case: PolicyCase) -> list[dict[str, object]]:
    """Read the trusted scenario's original input records.

    Args:
        case: Immutable original policy scenario.

    Returns:
        Original recorded input fields.
    """
    return cast(list[dict[str, object]], case["input"])
