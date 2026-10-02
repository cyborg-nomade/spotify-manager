"""Discovery catalog ranking retains edition preference and deterministic tie rules."""

from dataclasses import replace

import pytest

from spotify_manager.domain.discovery import RankedRelease
from spotify_manager.domain.discovery_catalog import canonical_releases
from spotify_manager.domain.discovery_catalog import ordered_catalog_tracks
from tests.support.discovery_values import release
from tests.support.discovery_values import track


BASE = release("album")


@pytest.mark.parametrize(
    "preferred,other",
    [
        (
            replace(BASE, saved=True, plain=False, popularity=0),
            replace(BASE, popularity=100),
        ),
        (
            replace(BASE, plain=True, popularity=0),
            replace(BASE, plain=False, popularity=100),
        ),
        (replace(BASE, popularity=0), replace(BASE, popularity=None)),
        (replace(BASE, popularity=80), replace(BASE, popularity=20)),
        (replace(BASE, top_track_rank=2), replace(BASE, top_track_rank=None)),
        (replace(BASE, top_track_rank=2), replace(BASE, top_track_rank=0)),
        (replace(BASE, total_tracks=1), replace(BASE, total_tracks=2)),
        (replace(BASE, release_date="1999"), replace(BASE, release_date="2020")),
        (replace(BASE, name="Alpha"), replace(BASE, name="Zulu")),
    ],
)
def test_edition_preferences_keep_original_precedence(
    preferred: RankedRelease, other: RankedRelease
) -> None:
    """Canonical selection preserves each original saved/plain/rank tie breaker.

    Args:
        preferred: Expected canonical edition.
        other: Edition losing at one original comparison field.
    """
    assert canonical_releases((other, preferred)) == (preferred,)
    assert canonical_releases((preferred, other)) == (preferred,)


def test_equal_edition_keys_retain_first_observed_edition() -> None:
    """Edition selection intentionally has no ID tiebreaker."""
    first = replace(BASE, spotify_id="z")
    second = replace(BASE, spotify_id="a")
    assert canonical_releases((first, second)) == (first,)
    assert canonical_releases((second, first)) == (second,)


def test_distinct_tiers_keep_same_title_as_separate_catalog_entries() -> None:
    """Identity groups retain their release-tier distinction before global ranking."""
    live = replace(BASE, spotify_id="live", tier=2, popularity=100)
    single = replace(BASE, spotify_id="single", tier=1, popularity=100)
    assert canonical_releases((live, single, BASE)) == (BASE, single, live)
    assert canonical_releases(()) == ()


@pytest.mark.parametrize(
    "preferred,other",
    [
        (replace(BASE, popularity=0), replace(BASE, popularity=None)),
        (replace(BASE, popularity=80), replace(BASE, popularity=20)),
        (replace(BASE, top_track_rank=1), replace(BASE, top_track_rank=2)),
        (replace(BASE, top_track_rank=2), replace(BASE, top_track_rank=0)),
        (replace(BASE, release_date="1999"), replace(BASE, release_date="2020")),
        (replace(BASE, name="Alpha"), replace(BASE, name="Zulu")),
    ],
)
def test_review_order_preserves_original_popularity_rank_date_and_title_rules(
    preferred: RankedRelease, other: RankedRelease
) -> None:
    """Review ordering remains distinct from edition selection.

    Args:
        preferred: Entry expected first in review order.
        other: Entry expected after it.
    """
    preferred = replace(preferred, identity="first", spotify_id="z")
    other = replace(other, identity="second", spotify_id="a")
    assert canonical_releases((other, preferred)) == (preferred, other)


def test_equal_review_keys_use_identifier_after_casefolded_title() -> None:
    """Distinct identities with equal display/ranking facts retain ID ordering."""
    first = replace(BASE, spotify_id="a", identity="first", name="TITLE")
    second = replace(BASE, spotify_id="z", identity="second", name="title")
    assert canonical_releases((second, first)) == (first, second)


def test_disc_track_order_retains_duplicate_position_order() -> None:
    """Catalog ordering never deduplicates or reorders equal track positions."""
    first = track("first")
    duplicate_position = track("other")
    second = replace(track("second"), track_number=2)
    other_disc = replace(track("disc"), disc_number=2)
    assert ordered_catalog_tracks((other_disc, second, duplicate_position, first)) == (
        duplicate_position,
        first,
        second,
        other_disc,
    )
    assert ordered_catalog_tracks(()) == ()
