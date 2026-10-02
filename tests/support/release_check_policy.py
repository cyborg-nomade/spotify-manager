"""Decode immutable original release-policy scenarios without clients or routines."""

import json
from pathlib import Path
from typing import cast

from spotify_manager.domain.release_check_values import ReleaseCandidate


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/release_check_policy.json"
)


def release(raw: dict[str, object]) -> ReleaseCandidate:
    """Decode one trusted original observed release record.

    Args:
        raw: Immutable original model fields.

    Returns:
        Typed original release.

    Raises:
        KeyError: The immutable snapshot lacks a required original field.
    """
    return ReleaseCandidate(
        str(raw["spotify_id"]),
        str(raw["uri"]),
        str(raw["name"]),
        str(raw["release_type"]),
        str(raw["release_date"]),
        str(raw["release_date_precision"]),
        cast(int, raw["total_tracks"]),
        str(raw["primary_artist_id"]),
        str(raw["primary_artist_name"]),
    )


def cases(section: str = "cases") -> list[dict[str, object]]:
    """Read trusted original policy inputs and output oracles.

    Args:
        section: Original observed release or type-classification cases.

    Returns:
        Immutable original scenario records.

    Raises:
        KeyError: The section is absent.
        OSError: The original fixture cannot be read.
        ValueError: The original fixture cannot be decoded.
    """
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text())[section])
