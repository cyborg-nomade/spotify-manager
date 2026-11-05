"""Exact metadata, availability, credits and saved-status boundaries for additions."""

from dataclasses import dataclass
from dataclasses import field
from typing import cast

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.application.discography_values import DiscographyAlbumError
from spotify_manager.application.ports.runtime import NoRetry
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.infrastructure.discography_linked_albums import (
    DiscographyLinkedAlbums,
)
from spotify_manager.infrastructure.discography_records import linked_release
from tests.routines.test_discography import raw_release
from tests.support.discography_review import FIRST
from tests.support.discography_review import SECOND


def _album() -> dict[str, object]:
    return raw_release(
        FIRST, "An explicit record", release_date="2003", artist_id="other"
    )


@dataclass
class AlbumSpotify:
    """Observe native-shaped exact reads without exposing the complete SDK.

    Args:
        metadata: Raw album data or a scripted Spotify failure.
        saved: Raw saved-membership response.
        calls: Ordered exact SDK observations.
    """

    metadata: object
    saved: object = field(default_factory=list)
    calls: list[tuple[str, object]] = field(default_factory=list)

    async def album(self, identity: str) -> object:
        """Return the exact requested album or raise its Spotify failure.

        Args:
            identity: Exact validated album ID.

        Returns:
            Raw metadata for boundary validation.

        Raises:
            SpotifyException: The scripted external failure occurs.
        """
        self.calls.append(("album", identity))
        if isinstance(self.metadata, SpotifyException):
            raise self.metadata
        return self.metadata

    async def current_user_saved_albums_contains(self, ids: list[str]) -> object:
        """Return one membership observation after valid metadata.

        Args:
            ids: Exact singleton album batch.

        Returns:
            Scripted unchecked membership data.
        """
        self.calls.append(("saved", ids))
        return self.saved


@pytest.mark.parametrize("saved", [False, True])
async def test_exact_album_and_saved_observations_keep_foreign_credits(
    saved: bool,
) -> None:
    """An explicitly linked release is not rejected for another primary artist.

    Args:
        saved: Observed saved-album membership.
    """
    spotify = AlbumSpotify(_album(), [saved])
    result = await DiscographyLinkedAlbums(
        cast(SpotifyClient, spotify), NoRetry()
    ).album(FIRST)
    assert result.linked and result.artists == ("Artist",)
    assert result.release.spotify_id == FIRST and result.release.saved is saved
    assert result.release.default is False
    assert spotify.calls == [("album", FIRST), ("saved", [FIRST])]


@pytest.mark.parametrize("status", [404, 410])
async def test_unavailable_album_is_a_recoverable_addition_failure(status: int) -> None:
    """Missing album errors can be presented without aborting the whole draft.

    Args:
        status: Spotify's unavailable-resource status.
    """
    spotify = AlbumSpotify(SpotifyException(status, -1, "Unavailable"))
    with pytest.raises(DiscographyAlbumError, match="could not find"):
        await DiscographyLinkedAlbums(cast(SpotifyClient, spotify), NoRetry()).album(
            FIRST
        )
    assert spotify.calls == [("album", FIRST)]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_other_spotify_errors_remain_owned_by_existing_retry_policy(
    status: int,
) -> None:
    """Authentication, limits and service errors cannot become missing-match notices.

    Args:
        status: Original Spotify failure category.
    """
    failure = SpotifyException(status, -1, "Failure")
    spotify = AlbumSpotify(failure)
    with pytest.raises(SpotifyException) as caught:
        await DiscographyLinkedAlbums(cast(SpotifyClient, spotify), NoRetry()).album(
            FIRST
        )
    assert caught.value is failure


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", SECOND),
        ("name", ""),
        ("name", None),
        ("artists", []),
        ("total_tracks", 0),
        ("total_tracks", -1),
        ("total_tracks", True),
        ("total_tracks", "10"),
        ("total_tracks", 2.5),
        ("album_type", []),
        ("album_type", "unknown"),
        ("is_playable", False),
        ("restrictions", {"reason": "market"}),
    ],
)
def test_malformed_or_restricted_metadata_cannot_be_selected(
    field: str, value: object
) -> None:
    """An unconfirmed bad record leaves existing choices untouched.

    Args:
        field: Metadata field to invalidate.
        value: Unsupported field value.
    """
    raw = _album()
    raw[field] = value
    with pytest.raises(DiscographyAlbumError):
        linked_release(raw, FIRST)


@pytest.mark.parametrize("raw", [None, [], "album"])
def test_missing_metadata_is_rejected(raw: object) -> None:
    """A successful transport without a usable album is not an addition.

    Args:
        raw: Unsupported response container.
    """
    with pytest.raises(DiscographyAlbumError):
        linked_release(raw, FIRST)


@pytest.mark.parametrize("saved", [None, [], [True, False], [1], ["yes"], {}])
async def test_invalid_saved_status_is_not_guessed(saved: object) -> None:
    """Only a checked boolean singleton can establish saved membership.

    Args:
        saved: Malformed membership observation.
    """
    spotify = AlbumSpotify(_album(), saved)
    with pytest.raises(DiscographyAlbumError, match="saved-album status"):
        await DiscographyLinkedAlbums(cast(SpotifyClient, spotify), NoRetry()).album(
            FIRST
        )


@pytest.mark.parametrize(
    "kind,name,total,expected",
    [
        ("single", "A single", 1, "Single"),
        ("single", "An EP", 5, "EP"),
        ("album", "Live at home", 12, "Live"),
        ("compilation", "Collected records", 12, "Compilation"),
    ],
)
def test_explicit_optional_release_categories_remain_available(
    kind: str, name: str, total: int, expected: str
) -> None:
    """Direct additions can include singles, compilations and live releases.

    Args:
        kind: Spotify album classification.
        name: Display title used by existing classification rules.
        total: Positive track count.
        expected: Human-readable offered category.
    """
    raw = _album()
    raw.update(album_type=kind, name=name, total_tracks=total)
    result = linked_release(raw, FIRST)
    assert result.release.release_type == expected and not result.release.default
