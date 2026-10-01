"""Verify rolling dormancy and the original top/catalog track tie preferences."""

from datetime import date

import pytest

from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.dormant_artists import eligible_artists
from spotify_manager.domain.dormant_artists import most_popular
from spotify_manager.domain.history import Scrobble


def _play(artist: str) -> Scrobble:
    return Scrobble("Song", artist, "Album", 0)


def _track(
    name: str, popularity: int | None, disc: int = 1, position: int = 1
) -> CatalogTrack:
    return CatalogTrack(
        name, name, name, disc, position, "artist", "Artist", popularity
    )


def test_dormant_intersection_counts_names_and_current_exclusions() -> None:
    """Protect all-year intersection, first display, repeats and ignored dates/keys."""
    history = {}
    for year in range(2022, 2026):
        history[date(year, 1, 1)] = [
            _play("Zulu"),
            _play("Beta"),
            _play("Current"),
            _play(" "),
        ]
    history[date(2021, 1, 1)] = [_play("Outside")]
    history[date(2027, 1, 1)] = [_play("Outside")]
    history[date(2022, 2, 1)] = [_play("ZULU"), _play("Once")]
    history[date(2026, 1, 1)] = [_play("Current")]
    result = eligible_artists(history, 2026)
    assert [(artist.key, artist.name, artist.scrobbles) for artist in result] == [
        ("beta", "Beta", 4),
        ("zulu", "Zulu", 5),
    ]


def test_dormant_empty_year_excludes_other_years() -> None:
    """Require every prior year even if all other years contain an artist."""
    history = {date(2025, 1, 1): [_play("Artist")]}
    assert eligible_artists(history, 2026) == ()


@pytest.mark.parametrize("top", [False, True])
def test_no_liked_tracks(top: bool) -> None:
    """Return no preferred marker for an empty observed set.

    Args:
        top: Original preference mode.
    """
    assert most_popular((), top) is None


def test_top_track_ties_use_track_position_then_descending_name() -> None:
    """Preserve unknown popularity fallback and ignore disc in top-track ties."""
    tracks = (
        _track("Unknown", None),
        _track("Position", 50, 1, 2),
        _track("Alpha", 50, 1, 1),
        _track("Zulu", 50, 3, 1),
    )
    assert most_popular(tracks, True) is tracks[3]


def test_catalog_ties_use_disc_before_track_and_descending_name() -> None:
    """Retain lower disc/position and descending title for equal catalog popularity."""
    tracks = (
        _track("Unknown", None),
        _track("Later disc", 50, 2),
        _track("Later position", 50, 1, 2),
        _track("Alpha", 50),
        _track("Zulu", 50),
    )
    assert most_popular(tracks, False) is tracks[4]


def test_artist_mapping_retains_original_observed_fields() -> None:
    """Keep raw mapping display/identity fields and nullable observed statistics."""
    from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate

    observed = SpotifyArtistCandidate(" id ", " Artist ", "uri", None, None, 2, False)
    assert observed.spotify_id == " id " and observed.name == " Artist "
    assert observed.popularity is None and observed.followers is None
    assert observed.search_rank == 2 and observed.exact_name is False
