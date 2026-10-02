"""Compare artist-review policies with immutable original observed decisions."""

import json
from dataclasses import asdict
from pathlib import Path
from typing import cast

import pytest

from spotify_manager.domain.artist_review_selection import ambiguous_track_choices
from spotify_manager.domain.artist_review_selection import earliest_releases
from spotify_manager.domain.artist_review_selection import log_int
from spotify_manager.domain.artist_review_selection import normalize_name
from spotify_manager.domain.artist_review_selection import queue_check_order
from spotify_manager.domain.artist_review_selection import release_date_key
from spotify_manager.domain.artist_review_selection import release_type
from spotify_manager.domain.artist_review_selection import spotify_search_query
from spotify_manager.domain.artist_review_values import ArtistReviewError
from spotify_manager.domain.artist_review_values import QueuePlaylists
from spotify_manager.domain.artist_review_values import ReleaseCandidate
from spotify_manager.domain.artist_review_values import TrackCandidate


Raw = dict[str, object]


def _cases() -> list[Raw]:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures/refactor/artist_review_policies.json"
    )
    return cast(list[Raw], json.loads(path.read_text()))


def _track(raw: Raw) -> TrackCandidate:
    return TrackCandidate(
        cast(str, raw["spotify_id"]),
        cast(str, raw["name"]),
        cast(str, raw["uri"]),
        cast(str, raw["album"]),
        cast(int, raw["rank"]),
        cast(str, raw["primary_artist_id"]),
        cast(str, raw["primary_artist_name"]),
        tuple(cast(list[str], raw["artist_ids"])),
        cast(int | None, raw["popularity"]),
    )


def _release(date: str, first: str | None = "a-first") -> ReleaseCandidate:
    return ReleaseCandidate(
        "album",
        "Album",
        "spotify:album:album",
        "Album",
        date,
        10,
        1,
        "a",
        "A",
        ("a",),
        True,
        first,
        "First",
        "spotify:track:first",
        "a",
        "A",
    )


def _outcome(case: Raw) -> object:
    kind = case["kind"]
    if kind in {"log-int", "query", "type"}:
        return _extra_policy(case)
    if kind == "choices":
        tracks = [_track(raw) for raw in cast(list[Raw], case["items"])]
        return [asdict(track) for track in ambiguous_track_choices(tracks)]
    if kind == "date":
        return release_date_key(_release(cast(str, case["value"])))
    if kind == "tier":
        return QueuePlaylists("one", "two", "three").for_liked_count(
            cast(int, case["value"])
        )
    if kind == "references":
        return _references(cast(list[str | None], case["values"]))
    if kind == "normalize":
        return normalize_name(cast(str, case["value"]))
    return _release("2000", cast(str | None, case["first"])).is_eligible_for(
        cast(str, case["value"])
    )


def _extra_policy(case: Raw) -> object:
    if case["kind"] == "log-int":
        return log_int(case["value"])
    if case["kind"] == "query":
        return spotify_search_query(cast(str, case["value"]))
    return release_type(cast(str, case["value"]) or "unknown", cast(int, case["count"]))


def _references(values: list[str | None]) -> object:
    try:
        return {"value": asdict(QueuePlaylists.from_references(*values))}
    except ArtistReviewError as exc:
        return {"error": type(exc).__name__, "message": str(exc)}


@pytest.mark.parametrize("case", _cases())
def test_review_policy_matches_original_decision(case: Raw) -> None:
    """Retain exact ties, chronology, configuration guards and first-credit rules.

    Args:
        case: Immutable original policy inputs and output.
    """
    actual = json.loads(json.dumps(_outcome(case)))
    assert actual == case["outcome"]


def test_queue_lookup_priority_retains_original_middle_first_high_tier() -> None:
    """Keep original queue lookup order on both sides of the five-like boundary."""
    queues = ("one", "two", "three")
    assert queue_check_order(queues, 5) == queues
    assert queue_check_order(queues, 6) == ("two", "three", "one")


def test_earliest_selection_replaces_duplicate_dates_before_the_ten_release_cap() -> (
    None
):
    """Retain last duplicates, chronological selection and displayed reranking."""
    candidates = []
    for index in range(11):
        release = _release(str(2000 + index))
        release.spotify_id = str(index)
        candidates.append(release)
    replacement = _release("2015")
    replacement.spotify_id = "0"
    candidates.append(replacement)
    selected = earliest_releases(candidates)
    identities = [release.spotify_id for release in selected]
    expected = [str(index) for index in range(1, 11)]
    assert identities == expected
    assert [release.rank for release in selected] == list(range(1, 11))
    assert selected[0] is candidates[1]
    assert earliest_releases([]) == []
