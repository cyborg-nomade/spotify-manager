"""Exercise original rotations, choices, classifications, history and index rules."""

import json
from dataclasses import asdict
from dataclasses import replace
from datetime import UTC
from datetime import date
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.catalog import ReleaseCandidate
from spotify_manager.domain.discography_batches import format_indexes
from spotify_manager.domain.discography_batches import next_queue
from spotify_manager.domain.discography_batches import next_start_queue
from spotify_manager.domain.discography_batches import parse_indexes
from spotify_manager.domain.discography_batches import queue_cycle
from spotify_manager.domain.discography_batches import removal_markers
from spotify_manager.domain.discography_batches import selected_releases
from spotify_manager.domain.discography_catalog import canonical_releases
from spotify_manager.domain.discography_catalog import catalog_type
from spotify_manager.domain.discography_history import dated_artists
from spotify_manager.domain.discography_history import ranked_artists
from spotify_manager.domain.discography_history import selected_artist
from spotify_manager.domain.discography_queues import marker_groups
from spotify_manager.domain.discography_queues import queue_artists
from spotify_manager.domain.discography_values import ArtistMarkers
from spotify_manager.domain.discography_values import ArtistSelection
from spotify_manager.domain.discography_values import CatalogRelease
from spotify_manager.domain.discography_values import DiscographyPlan
from spotify_manager.domain.discography_values import QueueName
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.releases import studio_release_type


NOW = datetime(2026, 8, 8, tzinfo=UTC)


def _rankings() -> list[dict[str, object]]:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures/refactor/discography_rankings.json"
    )
    return cast(list[dict[str, object]], json.loads(path.read_text()))


def _release(identity: str, default: bool = True) -> CatalogRelease:
    return CatalogRelease(
        identity,
        f"spotify:album:{identity}",
        identity,
        "Album",
        "2020",
        "2020",
        10,
        identity,
        False,
        True,
        0,
        default,
    )


def _marker(identity: str, artist: str, name: str) -> PlaylistTrack:
    album = ReleaseCandidate("album", "uri", "Album", "Album", "2020", 10, artist, name)
    return PlaylistTrack(identity, identity, identity, artist, name, album)


@pytest.mark.parametrize(
    "start,packing,rotation",
    [
        ("newfoundland", "memory_lane", "requeue"),
        ("memory_lane", "requeue", "newfoundland"),
        ("requeue", "newfoundland", "memory_lane"),
    ],
)
def test_discography_priority_cycles_remain_independent(
    start: QueueName, packing: QueueName, rotation: QueueName
) -> None:
    """Retain original distinct within-run and between-run priority.

    Args:
        start: Original first source.
        packing: Original next packing source.
        rotation: Original next-run first source.
    """
    assert queue_cycle(start)[0] == start
    assert next_queue(start) == packing
    assert next_start_queue(start) == rotation


@pytest.mark.parametrize(
    "text,total,expected",
    [
        ("", 0, ()),
        (", ,", 0, ()),
        ("3,1-3,2", 3, (3, 1, 2)),
        (" 1 - 2 ", 2, (1, 2)),
    ],
)
def test_discography_indexes_keep_first_requested_order(
    text: str, total: int, expected: tuple[int, ...]
) -> None:
    """Retain unique first-requested positions and empty parts.

    Args:
        text: Original requested expression.
        total: Original catalog size.
        expected: Original ordered positions.
    """
    assert parse_indexes(text, total) == expected


@pytest.mark.parametrize(
    "text,message",
    [
        ("3-1", "range start exceeds range end"),
        ("0", "release number out of range"),
        ("4", "release number out of range"),
        ("-1", "invalid literal"),
        ("x", "invalid literal"),
    ],
)
def test_discography_indexes_keep_original_errors(text: str, message: str) -> None:
    """Retain original range validation and native integer errors.

    Args:
        text: Original invalid expression.
        message: Original error text.
    """
    with pytest.raises(ValueError, match=message):
        parse_indexes(text, 3)


@pytest.mark.parametrize(
    "indexes,expected",
    [
        ((), "n"),
        ((3, 1, 2, 2, 5, 7, 8), "1-3,5,7-8"),
        ((0, -1, 4), "-1-0,4"),
        ((1,), "1"),
    ],
)
def test_discography_index_formatting_keeps_tolerant_compaction(
    indexes: tuple[int, ...], expected: str
) -> None:
    """Retain formatting without introducing catalog-range validation.

    Args:
        indexes: Original selected positions.
        expected: Original compressed expression.
    """
    assert format_indexes(indexes) == expected


def test_discography_choices_keep_catalog_order_and_marker_authority() -> None:
    """Retain catalog order, invalid-choice rejection and Newfoundland authority."""
    catalog = (_release("a"), _release("b"))
    assert selected_releases(catalog, ("b", "a")) == catalog
    assert selected_releases(catalog, ("a", "a")) is None
    assert selected_releases(catalog, ("x",)) is None
    assert selected_releases(catalog, ()) == ()
    extra = ArtistMarkers("queue_3", "extra", ("a",))
    local = ArtistMarkers("memory_lane", "local", ("b",))
    authority = ArtistMarkers("newfoundland", "nf", ("c",))
    assert removal_markers((extra, local)) == (local,)
    assert removal_markers((extra, authority)) == (extra, authority)


@pytest.mark.parametrize("case", _rankings())
def test_discography_artist_ranking_matches_original_spellings(
    case: dict[str, object],
) -> None:
    """Retain normalized identity, majority display spelling and ties.

    Args:
        case: Original immutable dated artist spellings and ranking.
    """
    plays = []
    for name in cast(list[str], case["names"]):
        plays.append(Scrobble("Track", name, "Album", 1))
    assert [asdict(artist) for artist in ranked_artists(plays)] == case["result"]


def test_discography_dates_keep_inclusive_boundaries_and_seconds_wrap() -> None:
    """Retain sorted eligible dates, nonempty rankings and seconds rank selection."""
    first, cutoff = date(2020, 1, 1), date(2021, 1, 1)
    play = Scrobble("T", "Artist", "Album", 1)
    history = {
        cutoff: [play],
        first: [play],
        date(2019, 1, 1): [play],
        date(2020, 5, 1): [],
    }
    rankings = dated_artists(history, first, cutoff)
    assert set(rankings) == {first, cutoff}
    selected = selected_artist(rankings, cutoff, 1, NOW.replace(second=59))
    assert selected.selected_date == cutoff
    assert selected.position == 1
    with pytest.raises(IndexError):
        selected_artist(rankings, cutoff, 2, NOW)


@pytest.mark.parametrize(
    "kind,group,name,total,standard,expected",
    [
        ("single", "", "Song", 1, None, None),
        ("single", "", "EP", 1, None, "Other"),
        ("single", "", "Song", 4, "EP", "EP"),
        ("ep", "", "EP", 1, None, "Other"),
        ("album", "compilation", "Studio", 10, "Album", "Album"),
        ("compilation", "", "Studio", 10, None, "Compilation"),
        ("other", "compilation", "Studio", 10, None, "Compilation"),
        ("other", "", "Best Of", 10, None, "Compilation"),
        ("other", "", "Live!", 10, None, "Live"),
        ("album", "", "Soundtrack", 10, None, "Other"),
        ("other", "", "Unknown", 10, None, None),
    ],
)
def test_discography_optional_release_classification(
    kind: str,
    group: str,
    name: str,
    total: int,
    standard: str | None,
    expected: str | None,
) -> None:
    """Preserve standard priority and exact optional-release qualification.

    Args:
        kind: Original release type.
        group: Original release group.
        name: Original title.
        total: Original positive track count.
        standard: Original studio qualification.
        expected: Original selected classification.
    """
    assert catalog_type(kind, group, name, total, standard) == expected


@pytest.mark.parametrize(
    "kind,total,name,expected",
    [
        ("album", 0, "Studio", "Album"),
        ("ep", 0, "Record", "EP"),
        ("single", 4, "Record", "EP"),
        ("single", 1, "Record EP", "EP"),
        ("single", 1, "Song", None),
        ("compilation", 10, "Record", None),
    ],
)
def test_shared_studio_type_keeps_original_ep_qualification(
    kind: str, total: int, name: str, expected: str | None
) -> None:
    """Retain original shared studio/EP type rules.

    Args:
        kind: Original untrimmed casefolded type.
        total: Original tolerant count.
        name: Original title.
        expected: Original studio qualification.
    """
    assert studio_release_type(kind, total, name) == expected


def test_discography_canonical_groups_keep_saved_edition_and_earliest_date() -> None:
    """Prefer a saved decorated edition while retaining earliest group chronology."""
    plain = replace(_release("a"), identity="same", release_date="2010")
    saved = replace(
        _release("b"),
        identity="same",
        release_date="2020",
        saved=True,
        plain=False,
        edition_rank=1,
    )
    live = replace(
        _release("live", False),
        release_type="Live",
        identity="same",
        release_date="2000",
    )
    assert canonical_releases([plain, saved, live]) == (
        replace(live, chronology_date="2000"),
        replace(saved, chronology_date="2010"),
    )


def test_discography_queue_facts_keep_first_spellings_and_unique_uri_order() -> None:
    """Retain first primary display spelling and ordered unique marker identities."""
    tracks = (
        _marker("first", "a", "First"),
        _marker("second", "b", "Second"),
        _marker("first", "a", "Changed"),
        _marker("third", "a", "Changed"),
    )
    artists = queue_artists(tracks, "requeue")
    assert tuple(artist.name for artist in artists) == ("First", "Second")
    assert marker_groups(tracks, "requeue", "rq")["a"].uris == ("first", "third")
    assert queue_artists((), "requeue") == ()
    assert marker_groups((), "queue_3", "extra") == {}


def test_discography_complete_values_keep_original_count_and_duration_properties() -> (
    None
):
    """Retain original complete selection counts and half-day-per-release estimates."""
    selection = ArtistSelection(
        "a", "Alpha", "requeue", (_release("one"), _release("two")), ()
    )
    plan = DiscographyPlan("requeue", "memory_lane", (selection,), 2, 8)
    assert selection.release_count == 2
    assert selection.days == 1.0
    assert plan.days == 1.0
