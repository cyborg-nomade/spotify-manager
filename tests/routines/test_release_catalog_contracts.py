"""Freeze original release-check raw metadata tolerance before codec extraction."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.routines import release_check as legacy


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/release_check_codecs.json"
)


def _cases(section: str) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text())[section])


@pytest.mark.parametrize("case", _cases("artists"))
def test_original_release_artist_codec(case: dict[str, object]) -> None:
    """Retain original required identity and integer/follower metadata tolerance.

    Args:
        case: Immutable original raw observation and parsed result.
    """
    artist = legacy._spotify_artist(case["raw"], 7, "Artist")
    assert (asdict(artist) if artist is not None else None) == case["expected"]


@pytest.mark.parametrize("case", _cases("releases"))
def test_original_release_candidate_codec(case: dict[str, object]) -> None:
    """Retain exact primary credit, precision and original release-kind coercion.

    Args:
        case: Immutable original raw observation and parsed result.
    """
    release = legacy._release_candidate(case["raw"], "artist")
    assert (asdict(release) if release is not None else None) == case["expected"]


@pytest.mark.parametrize("case", _cases("tracks"))
def test_original_release_track_codec(case: dict[str, object]) -> None:
    """Retain original playable identity and zero/invalid position fallback.

    Args:
        case: Immutable original raw observation and parsed result.
    """
    track = legacy._track_candidate(case["raw"], 7)
    assert (asdict(track) if track is not None else None) == case["expected"]
