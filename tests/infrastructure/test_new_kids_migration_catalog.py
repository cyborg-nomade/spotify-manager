"""Missing editions are recoverable without swallowing service or retry failures."""

from typing import cast
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.application.new_kids_migration_selection import (
    MigrationReleaseMissingError,
)
from spotify_manager.application.ports.runtime import NO_RETRY
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.infrastructure.legacy.discovery import LegacyDiscoveryCatalog
from spotify_manager.infrastructure.new_kids_migration_catalog import (
    NewKidsMigrationCatalog,
)
from tests.support.discovery_values import release
from tests.support.discovery_values import track


@pytest.mark.parametrize("status", [401, 404, 410, 429, 503])
async def test_only_missing_release_errors_offer_edition_resolution(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Auth, throttling and outages retain their exact original exception.

    Args:
        monkeypatch: Scoped existing catalogue boundary replacement.
        status: Spotify response status at the read boundary.
    """
    error = SpotifyException(status, -1, "synthetic read failure")
    monkeypatch.setattr(LegacyDiscoveryCatalog, "tracks", AsyncMock(side_effect=error))
    catalog = NewKidsMigrationCatalog(cast(SpotifyClient, Mock()), NO_RETRY)
    expected = (
        MigrationReleaseMissingError if status in {404, 410} else SpotifyException
    )
    with pytest.raises(expected) as caught:
        await catalog.tracks(release("current"))
    assert (
        caught.value.__cause__ is error
        if status in {404, 410}
        else caught.value is error
    )


async def test_successful_exact_read_is_not_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Original track order and exact IDs cross the migration adapter unchanged.

    Args:
        monkeypatch: Scoped existing catalogue boundary replacement.
    """
    tracks = (track("first"), track("second"))
    monkeypatch.setattr(
        LegacyDiscoveryCatalog, "tracks", AsyncMock(return_value=tracks)
    )
    catalog = NewKidsMigrationCatalog(cast(SpotifyClient, Mock()), NO_RETRY)
    assert await catalog.tracks(release("current")) is tracks
