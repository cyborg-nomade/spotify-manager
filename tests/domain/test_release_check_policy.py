"""Validate release policies against original snapshots and boundary scenarios."""

from datetime import date
from typing import cast

import pytest

from spotify_manager.domain import release_check as policy
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.release_check_values import PlaylistEntry
from spotify_manager.domain.release_check_values import PlaylistMembership
from spotify_manager.domain.release_check_values import RankedArtist
from spotify_manager.domain.release_check_values import ReleaseTrack
from tests.support.release_check_policy import cases
from tests.support.release_check_policy import release


@pytest.mark.parametrize("case", cases())
def test_release_policy_original_oracle(case: dict[str, object]) -> None:
    """Preserve every original date, scope, title and window result without SDK imports.

    Args:
        case: Immutable original inputs and output oracle.
    """
    observed = release(cast(dict[str, object], case["release"]))
    interval = policy.release_date_interval(observed)
    dates = [day.isoformat() for day in interval] if interval else None
    rank = cast(int, case["rank"])
    assert dates == case["interval"]
    assert policy.release_scope_reason(observed, rank) == case["reason"]
    assert list(policy.release_tags(observed)) == case["tags"]
    assert list(policy.release_identity(observed)) == case["identity"]
    assert (
        policy.released_during(observed, date(2026, 8, 1), date(2026, 8, 31))
        == case["during"]
    )
    assert policy.future_record(observed, date(2026, 8, 31), rank) == case["future"]


@pytest.mark.parametrize("case", cases("types"))
def test_release_type_original_oracle(case: dict[str, object]) -> None:
    """Preserve original type coercion and EP classification boundaries.

    Args:
        case: Immutable original type inputs and outcome.
    """
    assert (
        policy.release_type(case["raw"], cast(int, case["count"]), str(case["name"]))
        == case["expected"]
    )


@pytest.mark.parametrize(
    "rank,new_vintage,singles",
    [(20, True, True), (21, True, False), (50, True, False), (51, False, False)],
)
def test_ranked_artist_boundaries(rank: int, new_vintage: bool, singles: bool) -> None:
    """Retain original rank boundaries for destinations and standalone singles.

    Args:
        rank: Original global artist rank.
        new_vintage: Original top-fifty eligibility.
        singles: Original top-twenty eligibility.
    """
    artist = RankedArtist("artist", "Artist", 100, rank)
    assert artist.is_new_vintage is new_vintage
    assert artist.accepts_all_singles is singles


def _plays(artist: str, count: int) -> tuple[Scrobble, ...]:
    return tuple(Scrobble("Song", artist, "", index) for index in range(count))


def test_release_artist_ranking_normalization_display_ties_and_minimum() -> None:
    """Protect count ties, majority spelling, blank artists and threshold ranks."""
    history = _plays("  Beyoncé  ", 50) + _plays("Beyonce", 50) + _plays("Most", 101)
    history += _plays("Alpha", 100) + _plays("Tiny", 99) + _plays(" ", 102)
    artists = policy.rank_artists(history)
    assert [(artist.name, artist.scrobbles, artist.rank) for artist in artists] == [
        ("Most", 101, 1),
        ("Alpha", 100, 2),
        ("Beyonce", 100, 3),
    ]
    assert policy.rank_artists(()) == ()


def test_release_playlist_membership_and_primary_artist_deduplication() -> None:
    """Retain first artist credits, unknown credits and qualifier identities."""
    entries = (
        PlaylistEntry("uri-one", "one", "Song (Live)", "artist", "Beyoncé"),
        PlaylistEntry("uri-two", "two", "Other", "artist", "Beyoncé"),
        PlaylistEntry("uri-empty", "", "", None, None),
        PlaylistEntry("uri-unknown", "unknown", "Title", None, None),
    )
    membership = policy.membership(entries)
    assert membership.track_ids == {"one", "two", "unknown"}
    assert membership.track_keys == {("beyonce", "song"), ("beyonce", "other")}
    assert membership.primary_artist_ids == {"artist"}
    assert policy.deduplicated_entries(entries) == (entries[0], entries[2], entries[3])


def test_release_playlist_track_and_artist_identity_checks() -> None:
    """Accept exact track IDs or normalized title keys and original artist IDs."""
    membership = PlaylistMembership({"exact"}, {("beyonce", "song")}, {"artist"})
    same = ReleaseTrack("other", "uri", "Song (Remastered)", "artist", "Beyoncé", 1, 1)
    absent = ReleaseTrack("absent", "uri", "Other", "artist", "Beyoncé", 1, 1)
    exact = ReleaseTrack("exact", "uri", "Other", "artist", "Beyoncé", 1, 1)
    assert policy.track_is_present(membership, same)
    assert policy.track_is_present(membership, exact)
    assert not policy.track_is_present(membership, absent)
    assert policy.artist_is_present(
        membership,
        SpotifyArtistCandidate("artist", "Artist", "uri", None, None, 1, True),
    )
    assert not policy.artist_is_present(
        membership,
        SpotifyArtistCandidate("other", "Artist", "uri", None, None, 1, True),
    )


def test_future_single_title_and_id_matches() -> None:
    """Retain qualifier-tolerant titles and exact IDs, regardless of credited artist."""
    track = ReleaseTrack("track", "uri", "Song (Live)", "other", "Other", 1, 1)
    assert policy.normalized_track_title("Song (Remastered)") == "song"
    assert policy.contains_single("different", "song", (track,))
    assert policy.contains_single("track", "different", (track,))
    assert not policy.contains_single("different", "unrelated", (track,))
    assert not policy.contains_single("different", "", (track,))
    assert not policy.contains_single("different", "song", ())
