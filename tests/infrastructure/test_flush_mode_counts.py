"""Verify bounded live count reads and complete-observation failures."""

from typing import cast
from unittest.mock import AsyncMock

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager.application.flush_mode import FlushModeCheckError
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.domain.flush_mode import QueueCounts
from spotify_manager.infrastructure.flush_mode_counts import SpotifyQueueCounts


async def test_totals_need_only_two_small_reads() -> None:
    """Unavailable marker rows still count because only Spotify's total is used."""
    client = AsyncMock()
    client.get.side_effect = [{"total": 2400}, {"total": 900}]
    result = await SpotifyQueueCounts(
        cast(SpotifyClient, client), "first", "second"
    ).read()
    assert result == QueueCounts(2400, 900)
    assert client.get.await_count == 2
    assert client.get.await_args_list[0].args == (
        "playlists/first/items",
        {"fields": "total", "limit": 1},
    )


@pytest.mark.parametrize(
    "raw", [None, {}, {"total": True}, {"total": -1}, {"total": "12"}]
)
async def test_invalid_second_count_rejects_the_whole_observation(raw: object) -> None:
    """No partial first-playlist result can change automatic policy.

    Args:
        raw: Invalid second endpoint response.
    """
    client = AsyncMock()
    client.get.side_effect = [{"total": 2400}, raw]
    with pytest.raises(FlushModeCheckError):
        await SpotifyQueueCounts(cast(SpotifyClient, client), "first", "second").read()


async def test_upstream_failure_is_an_explicit_check_error() -> None:
    """An upstream refusal retains the previous automatic decision."""
    client = AsyncMock()
    client.get.side_effect = SpotifyException(429, -1, "retry later")
    with pytest.raises(FlushModeCheckError, match="previous decision"):
        await SpotifyQueueCounts(cast(SpotifyClient, client), "first", "second").read()
