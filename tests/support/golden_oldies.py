"""Trusted original Golden Oldies ranking profiles for the retrospective wave."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

from spotify_manager.domain.history import Scrobble
from spotify_manager.routines import something_old as legacy


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/refactor/golden_oldies.json"


def plays(profile: str) -> tuple[Scrobble, ...]:
    """Build original play-order, count, spelling and timestamp boundary profiles.

    Args:
        profile: Named original history scenario.

    Returns:
        Original typed history in observation order.
    """
    if profile == "empty":
        return ()
    rows: list[Scrobble] = []
    for index in range(120):
        artist, track, stamp = _fields(profile, index)
        rows.append(Scrobble(track, artist, "Album", stamp))
    return tuple(rows)


def _fields(profile: str, index: int) -> tuple[str, str, int]:
    if profile == "minimum":
        return ("Forty Nine" if index < 49 else "Fifty", "Track", index)
    if profile == "exact-case":
        return ("Artist" if index < 60 else "ARTIST", "Track", index % 60)
    if profile == "accent":
        return ("Beyoncé" if index < 60 else "Beyonce", "Track", index % 60)
    if profile == "trimmed":
        return " Artist " if index % 2 else "Artist", " Track ", index
    if profile == "invalid-labels":
        return (
            " " if index < 40 else "Artist",
            " " if 40 <= index < 80 else "Track",
            index,
        )
    if profile == "tracks":
        return "Artist", f"Track {index % 12}", index
    if profile == "title-case":
        return "Artist", "Track" if index % 2 else "TRACK", index
    if profile == "floor":
        return "Alpha" if index < 60 else "Zulu", "Track", index % 2
    if profile == "negative":
        return "Artist", "Track", -index
    return "Artist", "Track", 120 - index


def original_outcome(profile: str) -> object:
    """Read the original ranking before extracting its domain owner.

    Args:
        profile: Original history profile.

    Returns:
        JSON-compatible original ranking and track counts.
    """
    result = legacy.rank_golden_oldies(plays(profile))
    return json.loads(json.dumps([asdict(artist) for artist in result]))


def cases() -> list[tuple[str, object]]:
    """Read immutable original Golden Oldies observations.

    Returns:
        Original profiles and frozen rankings.
    """
    raw = cast(dict[str, object], json.loads(FIXTURE.read_text()))
    return list(raw.items())
