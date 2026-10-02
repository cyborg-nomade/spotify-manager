"""Protect original public genre-source selection and preserved route decoding."""

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from spotify_manager.application.genre_values import GenreRevealSourceError
from spotify_manager.application.genre_values import GenreRevealStateError
from spotify_manager.infrastructure.genre_models import GenreRevealRunRequest
from spotify_manager.infrastructure.genre_models import GenreRevealStateUpdate
from spotify_manager.infrastructure.genre_sources import EveryNoisePlaylistParser
from spotify_manager.infrastructure.genre_sources import decode_route
from spotify_manager.infrastructure.genre_sources import first_track_uris
from spotify_manager.infrastructure.genre_sources import primary_playlist


ROUTE_PATTERN = re.compile(r"(?P<route>.*)", re.DOTALL)
TRACK_PATTERN = re.compile(r"spotify:track:[A-Za-z0-9]{22}")
TRACKS = tuple("spotify:track:" + str(index).zfill(22) for index in range(12))


def test_genre_parser_keeps_only_valid_anchors_and_original_document_order() -> None:
    """Discard nonanchors/invalid links, retaining valid links with missing labels."""
    parser = EveryNoisePlaylistParser()
    parser.feed(
        '<div href="https://open.spotify.com/playlist/ignored"></div>'
        '<a href="https://invalid/playlist/wrong">wrong</a>'
        '<a href="https://open.spotify.com/playlist/intro">intro</a>'
        '<a href="https://open.spotify.com/user/user/playlist/primary?si=value" '
        'title="Listen to the Sound of Genre on Spotify">primary</a>'
    )
    assert parser.links[0] == ("https://open.spotify.com/playlist/intro", "")
    assert primary_playlist(parser.links, "Genre") == parser.links[1][0]


def test_genre_primary_selection_uses_first_matching_link() -> None:
    """Keep the first primary link rather than sorting or deduplicating discoveries."""
    links = [
        ("intro", "listen to a shorter introduction"),
        ("first", "LISTEN TO THE SOUND OF Genre ON SPOTIFY"),
        ("second", "listen to the sound of Genre on spotify"),
    ]
    assert primary_playlist(links, "Genre") == "first"


@pytest.mark.parametrize(
    "links",
    [
        [],
        [("wrong", "listen to the sound of Genre elsewhere")],
        [("wrong", "other on spotify")],
    ],
)
def test_genre_source_missing_primary_keeps_original_error(
    links: list[tuple[str, str]],
) -> None:
    """Missing or differently labelled links retain the original source error.

    Args:
        links: Nonprimary discovered links.
    """
    with pytest.raises(
        GenreRevealSourceError, match="no primary Spotify playlist for Genre"
    ):
        primary_playlist(links, "Genre")


def test_genre_embed_tracks_deduplicate_before_taking_ten() -> None:
    """Repeated markers do not consume the original ten distinct-marker positions."""
    html = " ".join((TRACKS[0], TRACKS[0], *TRACKS[1:]))
    assert first_track_uris(html, TRACK_PATTERN, 10) == TRACKS[:10]
    with pytest.raises(GenreRevealSourceError, match="first 10 tracks"):
        first_track_uris(" ".join(TRACKS[:9]), TRACK_PATTERN, 10)


def test_genre_route_retains_order_duplicates_and_original_string_coercions() -> None:
    """Do not sort route entries or impose new uniqueness/extra-field constraints."""
    raw = [["Second", "second", "ignored"], [123, "123"], ["Second", "second"]]
    route = decode_route(json.dumps(raw), Path("route.html"), ROUTE_PATTERN, 3)
    assert [(entry.name, entry.slug, entry.position) for entry in route] == [
        ("Second", "second", 1),
        ("123", "123", 2),
        ("Second", "second", 3),
    ]
    assert decode_route("[]", Path("route.html"), ROUTE_PATTERN, 3) == ()


def test_genre_route_absent_pattern_keeps_original_location_error() -> None:
    """Report missing embedded data with its original asset location."""
    with pytest.raises(GenreRevealStateError, match="not found in route.html"):
        decode_route("[]", Path("route.html"), re.compile(r"absent(?P<route>.*)"), 3)


@pytest.mark.parametrize(
    "raw",
    [
        "invalid",
        "null",
        "{}",
        "[[]]",
        '[["Name"]]',
        '[["Name", "Upper"]]',
        '[[" padded", "slug"]]',
        '[["One", "one"], ["Two", "two"]]',
    ],
)
def test_genre_route_invalid_data_keeps_original_error_and_cause(raw: str) -> None:
    """Reject invalid syntax, shapes, entries and overlong routes.

    Args:
        raw: Invalid encoded route data for an original one-entry limit.
    """
    with pytest.raises(GenreRevealStateError, match="invalid in route.html"):
        decode_route(raw, Path("route.html"), ROUTE_PATTERN, 1)


@pytest.mark.parametrize("field,value", [("slug", "Upper"), ("name", " padded")])
def test_genre_request_validators_keep_original_pydantic_errors(
    field: str, value: str
) -> None:
    """Preserve source request validation at the Pydantic boundary.

    Args:
        field: Original request field.
        value: Invalid original value.
    """
    fields = {"slug": "genre", "name": "Genre", field: value}
    with pytest.raises(ValidationError):
        GenreRevealRunRequest(**fields)


def test_genre_models_preserve_completed_order_and_valid_request_values() -> None:
    """Keep original first-occurrence progress and valid request spelling."""
    assert GenreRevealStateUpdate(
        completed=["second", "first", "second"]
    ).completed == ["second", "first"]
    request = GenreRevealRunRequest(slug="genre123", name="Genre Name")
    assert request.slug == "genre123" and request.name == "Genre Name"
