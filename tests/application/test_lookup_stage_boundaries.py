"""Protect lookup preconditions, fresh membership and explicit cache bypasses."""

from dataclasses import dataclass
from dataclasses import field

import pytest

from spotify_manager.application import library_lookup_run as workflow
from spotify_manager.application import lookup_resolution as resolution
from spotify_manager.application.lookup_effects import AlbumLookup
from spotify_manager.application.lookup_effects import ArtistLookup
from spotify_manager.application.lookup_effects import CachedTracks
from spotify_manager.application.lookup_effects import LookupTrack
from spotify_manager.application.lookup_effects import TrackLookup
from spotify_manager.application.scrobble_lookup_run import latest_history_timestamp
from spotify_manager.domain.lookup_values import LiveAlbumCandidate
from spotify_manager.domain.lookup_values import ResolvedTrack
from spotify_manager.domain.lookup_values import SpotifyLookupResponseError
from spotify_manager.infrastructure.scrobble_lookup import checked_row
from spotify_manager.infrastructure.scrobble_lookup import checked_timestamp


@dataclass
class MembershipRead:
    """Supply independently recorded raw membership responses.

    Args:
        values: Original raw responses in request order.
        requests: Original requested identity batches.
    """

    values: list[object]
    requests: list[list[str]] = field(default_factory=list)

    def read(self, identifiers: list[str]) -> object:
        """Observe one ordered membership batch.

        Args:
            identifiers: Original requested identities including duplicates.

        Returns:
            Original unvalidated response.
        """
        self.requests.append(identifiers)
        return self.values.pop(0)


def unavailable(*arguments: object) -> object:
    """Reject unexpected observations before a required lookup reference.

    Args:
        arguments: Unexpected observation parameters.

    Raises:
        AssertionError: Lookup observes effects before validating its reference.
    """
    raise AssertionError(arguments)


def missing_artist(identifier: str) -> tuple[str, str] | None:
    """Return incomplete original direct metadata.

    Args:
        identifier: Original requested identity.

    Returns:
        No complete artist identity.
    """
    return None


def no_artists(name: str) -> list[tuple[str, str]]:
    """Supply no original name candidates.

    Args:
        name: Original name reference.

    Returns:
        Empty original candidate list.
    """
    return []


def test_lookup_reference_guards_precede_effects() -> None:
    """Reject missing original artist, album and track references before reads."""
    artist = ArtistLookup(missing_artist, no_artists)
    with pytest.raises(ValueError, match="name or artist_id"):
        resolution.artist(artist, None, None)
    with pytest.raises(SpotifyLookupResponseError, match="invalid artist"):
        resolution.artist(artist, None, "artist")
    with pytest.raises(ValueError, match="name or album_id"):
        resolution.album(
            AlbumLookup(unavailable_album, unavailable_albums), None, None, None
        )
    with pytest.raises(ValueError, match="name or track_id"):
        resolution.track(TrackLookup(unavailable_track, unavailable_tracks), None, None)


def unavailable_album(identifier: str) -> LiveAlbumCandidate:
    """Reject an unexpected album observation.

    Args:
        identifier: Unexpected identity.

    Raises:
        AssertionError: A guard invokes the direct observation.
    """
    raise AssertionError(identifier)


def unavailable_albums(name: str, artist: str | None) -> list[LiveAlbumCandidate]:
    """Reject an unexpected album search.

    Args:
        name: Unexpected title.
        artist: Unexpected artist constraint.

    Raises:
        AssertionError: A guard invokes the search observation.
    """
    raise AssertionError((name, artist))


def unavailable_track(identifier: str) -> ResolvedTrack:
    """Reject an unexpected direct track observation.

    Args:
        identifier: Unexpected identity.

    Raises:
        AssertionError: A guard invokes the observation.
    """
    raise AssertionError(identifier)


def unavailable_tracks(name: str) -> list[ResolvedTrack]:
    """Reject an unexpected track search.

    Args:
        name: Unexpected title.

    Raises:
        AssertionError: A guard invokes the observation.
    """
    raise AssertionError(name)


@pytest.mark.parametrize("raw", [None, {}, [], [True, False]])
def test_live_status_shape_is_preserved(raw: object) -> None:
    """Require one raw status per requested identity.

    Args:
        raw: Original malformed membership response.
    """
    source = MembershipRead([raw])
    with pytest.raises(SpotifyLookupResponseError, match="Liked Songs"):
        resolution.liked_statuses(["one"], source.read, 20)


def test_membership_keeps_duplicates_and_last_observation() -> None:
    """Preserve duplicate requests, truthy values and last-value identity overwrite."""
    source = MembershipRead([[True, ""], ["yes"]])
    assert resolution.liked_statuses(["one", "two", "one"], source.read, 2) == {
        "one": True,
        "two": False,
    }
    assert source.requests == [["one", "two"], ["one"]]
    assert resolution.liked_statuses([], source.read, 20) == {}


def empty_cache() -> dict[str, list[LookupTrack]]:
    """Supply original empty cache authority.

    Returns:
        Empty original cache.
    """
    return {}


def reject_cache_write(cache: dict[str, list[LookupTrack]]) -> None:
    """Reject publication when the original cache flag is disabled.

    Args:
        cache: Unexpected cache publication.

    Raises:
        AssertionError: Disabled caching publishes state.
    """
    raise AssertionError(cache)


def empty_tracks(identifier: str) -> list[LookupTrack]:
    """Supply an independently observed empty album.

    Args:
        identifier: Original requested album identity.

    Returns:
        Empty original track page result.
    """
    return []


def test_disabled_cache_does_not_publish() -> None:
    """Keep cache writes disabled after successful uncached fetching."""
    deps = CachedTracks(empty_cache, reject_cache_write, empty_tracks)
    assert workflow.tracklist(deps, "album", False, False) == ([], False)


def test_latest_history_ignores_older_matching_encounters() -> None:
    """Select the greatest matching timestamp rather than the last row."""
    rows: list[object] = [
        {"artist": "Artist", "track": "Track", "date": 2000},
        {"artist": "Artist", "track": "Track", "date": 1000},
    ]
    assert (
        latest_history_timestamp(
            rows, "track", "artist", checked_row, checked_timestamp
        )
        == 2000
    )
