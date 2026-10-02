"""Pre-extraction contracts for New Kids artist-completion observations."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest
from spotipy import Spotify

from spotify_manager.routines import new_kids
from tests.routines.test_new_kids import FakeSpotify
from tests.routines.test_new_kids import ranked_release
from tests.routines.test_new_kids import raw_release
from tests.routines.test_new_kids import raw_track


@dataclass
class Requests:
    """Retain retry descriptions in exact observation order.

    Args:
        descriptions: Accepted requests in invocation order.
    """

    descriptions: list[str] = field(default_factory=list)

    def call(self, operation: Callable[[], object], description: str) -> object:
        """Execute one synthetic Spotify request.

        Args:
            operation: Existing SDK operation.
            description: Existing user-visible retry description.

        Returns:
            Unchanged simulated response.
        """
        self.descriptions.append(description)
        return operation()


def _spotify() -> FakeSpotify:
    spotify = FakeSpotify()
    album = raw_release("album", "Album")
    first = raw_track("first", "Alpha", album)
    second = raw_track("second", "Zulu", album)
    guest = raw_track("guest", "Guest", album, artist_id="guest")
    spotify.release_tracks["album"] = [first, second, guest]
    spotify.liked_ids = {"first", "second", "guest"}
    spotify.saved_album_ids = {"album"}
    return spotify


@pytest.mark.parametrize("fallback", [False, True])
def test_original_assessment_order_and_popularity_fallback(
    monkeypatch: pytest.MonkeyPatch, fallback: bool
) -> None:
    """Primary credits count once and fallback ties choose the greatest title.

    Args:
        monkeypatch: Scoped fake top-track override.
        fallback: Whether Spotify's top-track list has no eligible tracks.
    """
    spotify = _spotify()
    if fallback:
        monkeypatch.setattr(
            spotify, "artist_top_tracks", Mock(return_value={"tracks": []})
        )
    requests = Requests()
    result = new_kids.assess_artist(
        cast(Spotify, spotify), "artist", (ranked_release("album"),), requests.call, {}
    )
    assert (
        result.liked_tracks,
        result.total_primary_tracks,
        result.saved_releases,
    ) == (2, 2, 1)
    assert result.reasons == ("all albums saved", "all tracks liked")
    assert (
        result.representative_track is not None
        and result.representative_track.spotify_id == "first"
    )
    assert result.top_liked_track is not None
    assert result.top_liked_track.spotify_id == ("second" if fallback else "first")
    expected = [
        "checking 1 Saved Albums",
        "loading Album at offset 0",
        "checking 2 Liked Songs",
        "loading top tracks for artist artist",
    ]
    expected.append(
        "loading popularity for 2 tracks" if fallback else "checking 2 top Liked Songs"
    )
    assert requests.descriptions == expected


def test_original_duplicate_catalog_reuses_tracks_and_first_marker_facts() -> None:
    """Repeated release IDs stay in saved requests but track reads remain cached."""
    spotify = _spotify()
    requests = Requests()
    album = ranked_release("album")
    catalog = (album, replace(album, name="Repeated"))
    result = new_kids.assess_artist(
        cast(Spotify, spotify), "artist", catalog, requests.call, {}
    )
    assert result.total_releases == 2 and result.saved_releases == 1
    assert result.total_primary_tracks == 2
    assert requests.descriptions[0] == "checking 2 Saved Albums"
    assert requests.descriptions.count("loading Album at offset 0") == 1


def test_original_empty_catalog_still_observes_top_tracks() -> None:
    """Completion observes artist top tracks even when there are no catalog releases."""
    spotify = _spotify()
    requests = Requests()
    result = new_kids.assess_artist(
        cast(Spotify, spotify), "artist", (), requests.call, {}
    )
    assert result.representative_track is None and not result.qualifies
    assert result.top_liked_track is not None
    assert requests.descriptions == [
        "loading top tracks for artist artist",
        "checking 2 top Liked Songs",
    ]
