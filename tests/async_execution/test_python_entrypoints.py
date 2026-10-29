"""Keep synchronous Python callers working through the native execution boundary."""

import inspect
import json
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from spotipy import Spotify

from spotify_manager.client.lastfm import LastFmRecentTrack
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history


@dataclass
class BlockingHistory:
    """Return original synchronous Last.fm observations without a live service.

    Args:
        calls: Recorded closed timestamp ranges and page limits.
    """

    calls: list[tuple[int, int, int]]

    def recent_tracks(
        self, *, from_timestamp: int, to_timestamp: int, limit: int = 200
    ) -> tuple[LastFmRecentTrack, ...]:
        """Observe the original request and return one newer play.

        Args:
            from_timestamp: Original inclusive lower bound.
            to_timestamp: Original inclusive upper bound.
            limit: Original page limit.

        Returns:
            A dated play newer than the saved export.
        """
        self.calls.append((from_timestamp, to_timestamp, limit))
        return (LastFmRecentTrack("Artist", "New", "Album", 3),)


CALLER_LABEL: ContextVar[str] = ContextVar("python_api_caller", default="missing")


def _context_page(*args: object, **kwargs: object) -> dict[str, object]:
    assert CALLER_LABEL.get() == "original caller"
    return {"items": [], "next": None}


async def test_sync_python_api_still_works_inside_an_existing_caller_loop() -> None:
    """Retain a blocking Python call without nesting or closing the caller's loop."""
    source = Mock(spec=Spotify)
    source._get.side_effect = _context_page
    token = CALLER_LABEL.set("original caller")
    try:
        result = blast_from_past.load_playlist_state(source, "destination")
        assert result.total_items == 0
        assert CALLER_LABEL.get() == "original caller"
    finally:
        CALLER_LABEL.reset(token)


def test_sync_history_reader_retains_merge_and_preview_effects(tmp_path: Path) -> None:
    """Return the completed original result without writing preview history.

    Args:
        tmp_path: Isolated caller-owned history and audit files.
    """
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            {
                "scrobbles": [
                    {
                        "track": "Old",
                        "artist": "Artist",
                        "album": "Album",
                        "date": 1000,
                    }
                ]
            }
        )
    )
    original = path.read_bytes()
    reader = BlockingHistory([])
    result = scrobble_history.refresh_scrobble_history(
        reader,
        export_path=path,
        legacy_delta_path=None,
        backup_dir=tmp_path / "backups",
        log_path=tmp_path / "audit",
        now=datetime.fromtimestamp(10, UTC),
        dry_run=True,
    )
    assert not inspect.isawaitable(result)
    assert result.live_scrobbles_added == 1 and result.total_scrobbles == 2
    assert reader.calls == [(1, 10, 200)]
    assert path.read_bytes() == original
    assert not (tmp_path / "backups").exists()
    assert not (tmp_path / "audit").exists()


def test_sync_spotify_override_retains_raw_arguments_and_session_ownership() -> None:
    """Keep a caller's overridden SDK method and return a completed playlist."""
    source = Mock(spec=Spotify)
    session = Mock()
    source._session = session
    source._get.return_value = {"items": [], "total": 7, "next": None}
    result = blast_from_past.load_playlist_state(source, "destination")
    assert not inspect.isawaitable(result) and result.total_items == 0
    source._get.assert_called_once_with(
        "playlists/destination/items", limit=50, offset=0
    )
    session.close.assert_not_called()


@pytest.mark.parametrize("error", [ValueError("original"), KeyboardInterrupt("stop")])
def test_sync_python_caller_receives_the_original_sdk_failure(
    error: ValueError | KeyboardInterrupt,
) -> None:
    """Preserve the exact failure object across the owned loop and worker.

    Args:
        error: Original overridden SDK failure or operator interruption.
    """
    source = Mock(spec=Spotify)
    source._get.side_effect = error
    with pytest.raises(type(error)) as observed:
        blast_from_past.load_playlist_state(source, "destination")
    assert observed.value is error
