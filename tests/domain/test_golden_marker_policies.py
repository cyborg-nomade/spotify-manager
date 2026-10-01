"""Protect Golden Oldies marker policies without SDKs or application startup."""

import pytest

from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.catalog import ReleaseTrack
from spotify_manager.domain.golden_markers import album_markers
from spotify_manager.domain.golden_markers import distinct_markers
from spotify_manager.domain.golden_markers import exact_artists
from spotify_manager.domain.golden_markers import from_match
from spotify_manager.domain.golden_markers import lastfm_markers
from spotify_manager.domain.golden_oldies import LastFmTrackStat
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history_matching import SpotifyTrackMatch


ARTIST = SpotifyArtistCandidate("artist", "Artist", "artist:artist", None, None, 1)
MATCH = SpotifyTrackMatch(
    "one", "track:one", "One", ("Artist",), "Album", 1, 1.0, None, 50
)
TRACK = SelectedTrack("one", "track:one", "One", "Album", ("Artist",), "source")


def test_exact_artist_policy_retains_normalized_labels_and_search_order() -> None:
    """Retain accent normalization and distinct original search positions."""
    other = SpotifyArtistCandidate("other", "Other", "artist:other", None, None, 2)
    assert exact_artists(" ARTIST ", (other, ARTIST, ARTIST)) == (ARTIST, ARTIST)
    assert exact_artists("Artist", ()) == ()


def test_lastfm_marker_policy_prefers_liked_and_skips_duplicate_or_unsafe() -> None:
    """Keep the first title's count when later titles select the same identity."""
    titles = (
        LastFmTrackStat("first", 30, 200),
        LastFmTrackStat("second", 20, 100),
        LastFmTrackStat("unsafe", 10, 50),
        LastFmTrackStat("empty", 5, 25),
    )
    unsafe = SpotifyTrackMatch(
        "unsafe", "track:unsafe", "Unsafe", ("Artist",), "Wrong", 1, 1.0, 0.1, 50
    )
    selected = lastfm_markers(titles, ((MATCH,), (MATCH,), (unsafe,), ()), set())
    assert selected == (from_match(MATCH, "Last.fm top tracks", 30),)
    assert lastfm_markers((), (), set()) == ()


def test_lastfm_marker_policy_retains_strict_title_group_pairing() -> None:
    """Reject differing lengths as the original strict zip does."""
    with pytest.raises(ValueError):
        lastfm_markers((LastFmTrackStat("one", 50, 100),), (), set())


@pytest.mark.parametrize("limit,length", [(0, 2), (-1, 2), (1, 1), (2, 2), (10, 2)])
def test_popular_marker_policy_caps_after_accepting_distinct_identity(
    limit: int,
    length: int,
) -> None:
    """Retain first identities and the original post-append cap check.

    Args:
        limit: Original configured cap boundary.
        length: Original expected selection size.
    """
    second = SelectedTrack("two", "track:two", "Two", "Album", ("Artist",), "source")
    result = distinct_markers((TRACK, TRACK, second), limit)
    assert result == (TRACK, second)[:length]
    assert distinct_markers((), limit) == ()


def test_album_marker_policy_retains_complete_tracklist_and_source() -> None:
    """Keep complete ordered album tracks, including duplicate identities."""
    release = DiscographyRelease(
        "album",
        "album:album",
        "Release",
        "EP",
        "2020",
        "2020",
        2,
        "artist",
        "Artist",
        "release",
        False,
        True,
        0,
    )
    track = ReleaseTrack("one", "track:one", "One", 1, 1)
    result = album_markers(release, (track, track), ARTIST)
    assert len(result) == 2
    assert result[0].artists == ("Artist",)
    assert result[0].source == "EP: Release"
    assert album_markers(release, (), ARTIST) == ()
