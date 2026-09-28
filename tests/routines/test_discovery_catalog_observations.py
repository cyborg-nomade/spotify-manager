"""Original Spotify catalog request order and tolerant parsing contracts."""

from typing import cast
from unittest.mock import Mock

import pytest
from spotipy import Spotify

from spotify_manager.routines import new_kids
from tests.routines.test_artist_assessment_observations import Requests
from tests.routines.test_new_kids import ranked_release
from tests.routines.test_new_kids import raw_release
from tests.routines.test_new_kids import raw_track


def test_catalog_pages_keep_first_id_order_and_last_simplified_record() -> None:
    """After pagination, membership and top-track reads precede detail batches."""
    sdk = Mock(spec=Spotify)
    sdk.artist_albums.side_effect = [
        {
            "items": [
                None,
                {},
                raw_release("a", "Original"),
                raw_release("guest", "Guest", artist_id="guest"),
            ],
            "next": "next",
        },
        {"items": [raw_release("a", "Updated"), raw_release("b", "B")], "next": None},
    ]
    sdk.current_user_saved_albums_contains.return_value = [True, False]
    sdk.artist_top_tracks.return_value = {"tracks": []}
    sdk.albums.return_value = {"albums": [None, {"id": ""}, raw_release("b", "Full B")]}
    requests = Requests()
    results = new_kids.load_ranked_catalog(cast(Spotify, sdk), "artist", requests.call)
    assert requests.descriptions == [
        "loading releases for artist artist at offset 0",
        "loading releases for artist artist at offset 4",
        "checking 2 Saved Albums",
        "loading top tracks for artist artist",
        "loading popularity for 2 releases",
    ]
    sdk.current_user_saved_albums_contains.assert_called_once_with(["a", "b"])
    sdk.albums.assert_called_once_with(["a", "b"])
    assert [(value.spotify_id, value.name, value.saved) for value in results] == [
        ("b", "Full B", False),
        ("a", "Updated", True),
    ]


def test_empty_primary_catalog_omits_all_downstream_observations() -> None:
    """Invalid or guest-only records do not trigger membership or popularity reads."""
    sdk = Mock(spec=Spotify)
    sdk.artist_albums.return_value = {
        "items": [None, {}, raw_release("guest", "Guest", artist_id="guest")]
    }
    requests = Requests()
    assert (
        new_kids.load_ranked_catalog(cast(Spotify, sdk), "artist", requests.call) == ()
    )
    assert requests.descriptions == ["loading releases for artist artist at offset 0"]
    sdk.current_user_saved_albums_contains.assert_not_called()
    sdk.artist_top_tracks.assert_not_called()
    sdk.albums.assert_not_called()


@pytest.mark.parametrize(
    "response", [None, {}, {"items": None}, {"items": [], "next": "next"}]
)
def test_invalid_catalog_pages_preserve_error_boundaries(response: object) -> None:
    """Malformed pages and empty continuation pages retain original validation."""
    sdk = Mock(spec=Spotify)
    sdk.artist_albums.return_value = response
    with pytest.raises(
        new_kids.NewKidsError, match="invalid artist releases|empty release page"
    ):
        new_kids.load_ranked_catalog(cast(Spotify, sdk), "artist", Requests().call)
    sdk.current_user_saved_albums_contains.assert_not_called()


def test_top_tracks_keep_raw_ranks_and_tolerant_metadata() -> None:
    """Top track filtering retains original ranks and tolerant metadata conversion."""
    sdk = Mock(spec=Spotify)
    album = raw_release("album", "Album")
    good = raw_track("good", "  Name  ", album)
    good.update(track_number=True, disc_number=-1, popularity=True)
    albumless = raw_track(
        "albumless", "", {"artists": [{"id": "artist", "name": "Artist"}]}
    )
    albumless.update(popularity="5", track_number=None)
    sdk.artist_top_tracks.return_value = {
        "tracks": [
            None,
            raw_track("guest", "Guest", album, artist_id="guest"),
            good,
            raw_track(
                "guest-album",
                "Guest Album",
                raw_release("other", "Other", artist_id="other"),
            ),
            albumless,
            good,
        ]
    }
    ranks, tracks = new_kids.load_top_track_data(
        cast(Spotify, sdk), "artist", Requests().call
    )
    assert ranks == {"album": 3}
    assert [track.spotify_id for track in tracks] == ["good", "albumless", "good"]
    assert [track.track_number for track in tracks] == [3, 5, 6]
    assert tracks[0].popularity is True and tracks[0].disc_number == 1
    assert tracks[0].name == "  Name  "
    assert tracks[1].popularity is None and tracks[1].name == "albumless"


@pytest.mark.parametrize("response", [None, {}, {"tracks": None}])
def test_invalid_top_track_container_preserves_original_error(response: object) -> None:
    """Top-track validation rejects missing or non-list track collections."""
    sdk = Mock(spec=Spotify)
    sdk.artist_top_tracks.return_value = response
    with pytest.raises(new_kids.NewKidsError, match="invalid artist top tracks"):
        new_kids.load_top_track_data(cast(Spotify, sdk), "artist", Requests().call)


def test_top_tracks_skip_missing_album_credit_and_track_identifiers() -> None:
    """Malformed records are omitted without rejecting the entire response."""
    sdk = Mock(spec=Spotify)
    valid = raw_track("track", "Track", raw_release("album", "Album"))
    sdk.artist_top_tracks.return_value = {
        "tracks": [
            {**valid, "album": None},
            {**valid, "album": {}},
            {**valid, "artists": []},
            {**valid, "id": ""},
            {**valid, "uri": ""},
            valid,
        ]
    }
    ranks, tracks = new_kids.load_top_track_data(
        cast(Spotify, sdk), "artist", Requests().call
    )
    assert ranks == {"album": 6} and len(tracks) == 1


def test_track_pages_count_raw_offsets_and_accepted_position_fallbacks() -> None:
    """Pagination counts all rows while fallback track positions count accepted rows."""
    sdk = Mock(spec=Spotify)
    album = raw_release("album", "Album")
    first = raw_track("first", "First", album)
    first.update(disc_number=2, track_number=0)
    second = raw_track("guest", "Guest", album, artist_id="guest")
    second.update(track_number=-1)
    sdk.album_tracks.side_effect = [
        {"items": [None, first], "next": "next"},
        {"items": [{"id": "no-credit"}, second], "next": None},
    ]
    requests = Requests()
    tracks = new_kids.load_release_tracks(
        cast(Spotify, sdk), ranked_release("album"), requests.call
    )
    assert [track.spotify_id for track in tracks] == ["guest", "first"]
    assert [track.track_number for track in tracks] == [2, 1]
    assert all(track.popularity is None for track in tracks)
    assert requests.descriptions == [
        "loading Album at offset 0",
        "loading Album at offset 2",
    ]
    assert sdk.album_tracks.call_args_list[-1].kwargs == {"limit": 50, "offset": 2}


@pytest.mark.parametrize(
    "response", [None, {}, {"items": None}, {"items": [], "next": "next"}]
)
def test_invalid_track_pages_keep_release_specific_errors(response: object) -> None:
    """Track page failures preserve the release name and original error category."""
    sdk = Mock(spec=Spotify)
    sdk.album_tracks.return_value = response
    with pytest.raises(
        new_kids.NewKidsError, match="invalid tracks for Album|empty page for Album"
    ):
        new_kids.load_release_tracks(
            cast(Spotify, sdk), ranked_release("album"), Requests().call
        )


@pytest.mark.parametrize("response", [None, {}, {"albums": None}])
def test_invalid_detail_batches_fail_after_membership_and_top_track_reads(
    response: object,
) -> None:
    """Detail validation retains all preceding accepted catalog observations."""
    sdk = Mock(spec=Spotify)
    sdk.artist_albums.return_value = {"items": [raw_release("album", "Album")]}
    sdk.current_user_saved_albums_contains.return_value = [False]
    sdk.artist_top_tracks.return_value = {"tracks": []}
    sdk.albums.return_value = response
    requests = Requests()
    with pytest.raises(new_kids.NewKidsError, match="invalid album details"):
        new_kids.load_ranked_catalog(cast(Spotify, sdk), "artist", requests.call)
    assert requests.descriptions[-3:] == [
        "checking 1 Saved Albums",
        "loading top tracks for artist artist",
        "loading popularity for 1 releases",
    ]
