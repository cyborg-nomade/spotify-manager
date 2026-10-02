"""Independent album identities, edition ambiguity and evidence scores."""

from dataclasses import replace
from datetime import date

import pytest

from spotify_manager.domain.album_recommendations import AlbumEvidence
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_recommendations import _AlbumAccumulator
from spotify_manager.domain.album_recommendations import canonical_album_key
from spotify_manager.domain.album_recommendations import eligible_release_type
from spotify_manager.domain.album_recommendations import genuinely_ambiguous
from spotify_manager.domain.album_recommendations import heard_album_keys
from spotify_manager.domain.album_recommendations import option_sort_key
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate
from tests.support.album_evidence import read_case
from tests.support.album_evidence import recommendation_records


WEEK = date(2026, 8, 7)


def _option() -> SpotifyAlbumOption:
    return read_case("duplicates").observations["Same"][0]


def _candidate() -> FoundArtCandidate:
    return read_case("duplicates").candidates[0]


@pytest.mark.parametrize(
    "name", ["grouped", "duplicates", "exclusions", "negative-limit", "empty"]
)
def test_original_album_score_and_weekly_rank_snapshots(name: str) -> None:
    """Match original first displays, bonuses, preferred editions and rotation exactly.

    Args:
        name: Original immutable evidence scenario.
    """
    case = read_case(name)
    evidence = AlbumEvidence(case.excluded, case.existing)
    for candidate in case.candidates[: case.maximum]:
        evidence.observe(candidate, case.observations[candidate.track])
    assert recommendation_records(evidence.ranked(WEEK)) == case.expected


def test_history_keys_exclude_missing_and_invalid_names_and_collapse_editions() -> None:
    """Keep original valid album identities independently of track titles."""
    plays = [
        Scrobble("", "Beyoncé", "Album", 0),
        Scrobble("Song", "Beyonce", "Album (Deluxe)", 0),
        Scrobble("Song", "Artist", "", 0),
        Scrobble("Song", " ", "Album", 0),
        Scrobble("Song", "Artist", " ", 0),
    ]
    assert heard_album_keys(plays) == {canonical_album_key("Beyonce", "Album")}
    assert heard_album_keys([]) == set()


@pytest.mark.parametrize(
    "field,value",
    [
        ("album", "Other"),
        ("release_date", "2025"),
        ("total_tracks", 11),
        ("release_type", "EP"),
    ],
)
def test_visible_metadata_ambiguity_requires_any_distinct_original_signature(
    field: str, value: str | int
) -> None:
    """Each original metadata component can require an edition prompt.

    Args:
        field: Original metadata component under comparison.
        value: Different original observed metadata.
    """
    first = _option()
    values: dict[str, str | int] = {
        "album": first.album,
        "release_date": first.release_date,
        "total_tracks": first.total_tracks,
        "release_type": first.release_type,
    }
    values[field] = value
    second = replace(
        first,
        album=str(values["album"]),
        release_date=str(values["release_date"]),
        total_tracks=int(values["total_tracks"]),
        release_type=str(values["release_type"]),
    )
    assert genuinely_ambiguous((first, second))


def test_ambiguity_ignores_ids_and_case_but_keeps_decorated_titles() -> None:
    """Choice signatures compare normalized visible titles and literal metadata."""
    first = _option()
    same = replace(first, spotify_id="other", artist="Other", album=first.album.upper())
    assert not genuinely_ambiguous(())
    assert not genuinely_ambiguous((first,))
    assert not genuinely_ambiguous((first, same))
    assert genuinely_ambiguous((first, replace(first, album=first.album + " (Deluxe)")))


def test_option_ties_retain_first_observation_and_sort_id_deterministically() -> None:
    """Equal edition ranks retain first metadata and order other IDs."""
    option = _option()
    tied = replace(option, source_track="Later display")
    other = replace(option, spotify_id="a", source_track="Other")
    evidence = AlbumEvidence(set(), set())
    evidence.observe(_candidate(), (option, tied, other))
    ranked = evidence.ranked(WEEK)[0]
    assert ranked.options == tuple(sorted((option, other), key=option_sort_key))
    assert ranked.options[0] == other


def test_accumulator_retains_explicit_support_and_edition_storage() -> None:
    """Preserve original constructor tolerance and caller-owned storage identity."""
    support = {"Original"}
    options = {"id": _option()}
    accumulator = _AlbumAccumulator(
        "Artist",
        "Album",
        ("artist", "album"),
        supporting_tracks=support,
        options=options,
    )
    assert accumulator.supporting_tracks is support and accumulator.options is options


@pytest.mark.parametrize("field", ["supporting_tracks", "options"])
def test_corrupted_storage_raises_after_original_score_updates(field: str) -> None:
    """Keep original assertion boundaries after weighted score and best-match updates.

    Args:
        field: Original initialized storage to corrupt.
    """
    evidence = AlbumEvidence(set(), set())
    option, candidate = _option(), _candidate()
    evidence.observe(candidate, (option,))
    accumulator = evidence.accumulators[
        canonical_album_key(option.artist, option.album)
    ]
    setattr(accumulator, field, None)
    with pytest.raises(AssertionError):
        evidence.observe(candidate, (option,))
    assert accumulator.score == 4 and accumulator.best_match == 0.95


def test_tolerant_projection_preserves_empty_storage_bonus_and_zero_best_floor() -> (
    None
):
    """Rank original corrupt-but-projectable storage without adding validation."""
    key = ("artist", "album")
    accumulator = _AlbumAccumulator("Artist", "Album", key, score=2)
    accumulator.supporting_tracks = None
    accumulator.options = None
    result = AlbumEvidence(set(), set(), {key: accumulator}).ranked(WEEK)[0]
    assert result.score == 1.7 and result.best_match == 0
    assert result.supporting_tracks == ()
    assert result.options == ()


def test_empty_normalized_observation_keys_remain_accepted() -> None:
    """Observation grouping does not inherit stricter heard-history filtering."""
    evidence = AlbumEvidence(set(), set())
    option = replace(_option(), artist=" ", album=" ")
    evidence.observe(replace(_candidate(), best_match=-1), (option,))
    result = evidence.ranked(WEEK)[0]
    assert result.key == ("", "") and result.best_match == 0


@pytest.mark.parametrize(
    "kind,total,name,expected",
    [
        ("album", 0, "Album", "Album"),
        ("ep", 0, "Album", "EP"),
        ("single", 3, "Album", None),
        ("single", 4, "Album", "EP"),
        ("compilation", 10, "Album", None),
        (None, 10, "Album", None),
        ("album", 10, "Album (Live)", None),
        ("album", 10, "Album (Deluxe)", None),
    ],
)
def test_original_plain_album_and_ep_release_eligibility(
    kind: object,
    total: int,
    name: str,
    expected: str | None,
) -> None:
    """Keep original release-tier and decoration precedence without new validation.

    Args:
        kind: Original raw release classification.
        total: Original coerced track count.
        name: Original stripped title.
        expected: Original eligible release type or exclusion.
    """
    assert eligible_release_type(kind, total, name) == expected
