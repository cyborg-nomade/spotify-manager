"""Freeze original release-check raw metadata tolerance before codec extraction."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.infrastructure.release_check_catalog import parse_artist
from spotify_manager.infrastructure.release_check_catalog import parse_release
from spotify_manager.infrastructure.release_check_catalog import parse_track


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/release_check_codecs.json"
)


def _cases(section: str) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], json.loads(FIXTURE.read_text())[section])


@pytest.mark.parametrize("case", _cases("artists"))
def test_codec_release_artist_codec(case: dict[str, object]) -> None:
    """Retain original required identity and integer/follower metadata tolerance.

    Args:
        case: Immutable original raw observation and parsed result.
    """
    artist = parse_artist(case["raw"], 7, "Artist")
    assert (asdict(artist) if artist is not None else None) == case["expected"]


@pytest.mark.parametrize("case", _cases("releases"))
def test_codec_release_candidate_codec(case: dict[str, object]) -> None:
    """Retain exact primary credit, precision and original release-kind coercion.

    Args:
        case: Immutable original raw observation and parsed result.
    """
    release = parse_release(case["raw"], "artist")
    assert (asdict(release) if release is not None else None) == case["expected"]


@pytest.mark.parametrize("case", _cases("tracks"))
def test_codec_release_track_codec(case: dict[str, object]) -> None:
    """Retain original playable identity and zero/invalid position fallback.

    Args:
        case: Immutable original raw observation and parsed result.
    """
    track = parse_track(case["raw"], 7)
    assert (asdict(track) if track is not None else None) == case["expected"]


@pytest.mark.parametrize(
    "raw",
    [None, [], {}, {"artists": None}, {"artists": {}}, {"artists": {"items": None}}],
)
def test_artist_search_requires_original_items_list(raw: object) -> None:
    """Reject original malformed search envelopes before parsing any row.

    Args:
        raw: Original untrusted response.
    """
    from spotify_manager.application.release_check_values import (
        ReleaseCheckSpotifyError,
    )
    from spotify_manager.infrastructure.release_check_catalog import parse_artist_search

    with pytest.raises(
        ReleaseCheckSpotifyError, match="invalid artist search data for Artist"
    ):
        parse_artist_search(raw, "Artist", parse_artist)


def test_artist_search_retains_raw_ranks_and_duplicate_observations() -> None:
    """Retain original raw positions after skipped rows and repeated identities."""
    from spotify_manager.infrastructure.release_check_catalog import parse_artist_search

    row = {"id": "artist", "uri": "uri", "name": "Artist"}
    observed = parse_artist_search(
        {"artists": {"items": [None, row, row]}}, "Artist", parse_artist
    )
    assert [artist.search_rank for artist in observed] == [2, 3]
    assert [artist.spotify_id for artist in observed] == ["artist", "artist"]


def test_release_artist_pairs_preserve_id_fallback_and_blank_names() -> None:
    """Ignore blank IDs and retain original blank names and ID fallback spelling."""
    from spotify_manager.infrastructure.release_check_catalog import artist_pairs

    observed = artist_pairs(
        [
            None,
            {"id": " ", "name": "Ignored"},
            {"id": " id ", "name": " "},
            {"id": "fallback"},
        ]
    )
    assert observed == (("id", ""), ("fallback", "fallback"))
