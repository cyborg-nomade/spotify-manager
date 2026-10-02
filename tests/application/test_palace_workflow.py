"""Replay original Palace runs and accepted-effect recovery through typed ports."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from typing import cast

import pytest

from spotify_manager.application.palace_effects import PalaceStateAccess
from spotify_manager.application.palace_run import Palace
from spotify_manager.application.palace_values import PalaceOfMemoryConfigError
from spotify_manager.application.palace_values import PalaceOfMemorySummary
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.palace_albums import cursor_index
from spotify_manager.domain.palace_values import HistoricalAlbumSelection
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.models.your_library import YourLibraryAlbum
from tests.support.palace_run import FIXTURE
from tests.support.palace_run import PalaceObservations
from tests.support.palace_run import albums
from tests.support.palace_run import cases
from tests.support.palace_run import history
from tests.support.palace_run import recovery_outcome
from tests.support.queue_neighbors import NOW


@dataclass(frozen=True)
class MemoryPalace:
    """Supply complete original Palace facts without live SDK or file operations.

    Args:
        edge: Original scenario and accepted-effect observations.
    """

    edge: PalaceObservations

    def progress(self, message: str) -> None:
        """Observe original progress.

        Args:
            message: Original visible stage.
        """
        self.edge.progress(message)

    def refresh(self) -> tuple[tuple[YourLibraryAlbum, ...], SavedAlbumRefresh]:
        """Supply original complete mirror publication facts.

        Returns:
            Original refreshed mirror and refresh summary.
        """
        self.edge.record("refresh", "albums", True)
        return albums(), SavedAlbumRefresh(NOW, 6, 7, 1, 0, 0, True, "backup")

    def state_access(self) -> PalaceStateAccess:
        """Supply original durable cursor authority.

        Returns:
            Original typed in-memory cursor boundary.
        """
        self.edge.record("state-access", "cursor", True)
        return self.edge

    def start_index(
        self,
        saved: tuple[YourLibraryAlbum, ...],
        manual: str | None,
        state: dict[str, object],
    ) -> int:
        """Supply original validated configuration or durable cursor facts.

        Args:
            saved: Original refreshed canonical mirror.
            manual: Original optional manual start.
            state: Original loaded durable facts.

        Returns:
            Original selected starting position.

        Raises:
            PalaceOfMemoryConfigError: The original manual reference is empty.
        """
        if manual == "":
            raise PalaceOfMemoryConfigError("Alphabetical start cannot be empty.")
        if manual is not None:
            return int(manual) - 1
        return cursor_index(
            saved,
            str(state.get("last_alphabetical_album_id") or ""),
            cast(int, state["next_alphabetical_index"]),
        )

    def historical(
        self,
    ) -> tuple[datetime, date, int, tuple[HistoricalAlbumSelection, ...]]:
        """Supply original complete historical selection.

        Returns:
            Original effective timestamp, cutoff, eligible dates and albums.
        """
        self.edge.record("history", "history", "2026-08-08", True)
        selected = () if self.edge.scenario == "empty-history" else history()
        return NOW, date(2025, 12, 31), 3, selected

    def playlist(self, recheck: bool) -> PlaylistState:
        """Supply original retry placement and current live membership.

        Args:
            recheck: Whether this is the final pre-write live check.

        Returns:
            Original configured playlist facts.
        """
        description = (
            "rechecking Palace of Memory" if recheck else "loading Palace of Memory"
        )
        self.edge.record("retry", description)
        self.edge.record("playlist", "destination")
        identities = set(self.edge.accepted)
        if self.edge.scenario == "initial-present":
            identities.add("track-album-1")
        if self.edge.scenario == "changed" and recheck:
            identities.add("track-remote")
        if self.edge.scenario == "all-present":
            identities.update(f"track-album-{index}" for index in range(7))
            identities.add("track-remote")
        return PlaylistState(len(identities), frozenset(identities))

    def first_track(self, album: SpotifyAlbum) -> SpotifyFirstTrack:
        """Supply original first-marker facts.

        Args:
            album: Original selected release.

        Returns:
            Original complete first marker.
        """
        self.edge.record("track", asdict(album))
        identity = f"track-{album.spotify_id}"
        return SpotifyFirstTrack(identity, f"spotify:track:{identity}", "First")

    def search(self, artist: str, album: str) -> SpotifyAlbum | None:
        """Supply original remote resolution or no-match facts.

        Args:
            artist: Original expected artist spelling.
            album: Original expected album title.

        Returns:
            Original remote edition or none.
        """
        self.edge.record("search", artist, album)
        if self.edge.scenario == "missing":
            return None
        return SpotifyAlbum("remote", "spotify:album:remote", artist, album, False, 1.0)

    def append(self, pending: tuple[SpotifyFirstTrack, ...]) -> None:
        """Accept original distinct pending markers through the original retry seam.

        Args:
            pending: Original ordered pending markers.
        """
        self.edge.record("retry", "adding first tracks to Palace of Memory")
        self.edge._post(
            "playlists/destination/items", {"uris": [track.uri for track in pending]}
        )

    def echo(self, message: str) -> None:
        """Observe original accepted-append presentation.

        Args:
            message: Original completion text.
        """
        self.edge.echo(message)

    def cursor_payload(
        self, next_index: int, last: YourLibraryAlbum
    ) -> dict[str, object]:
        """Build original complete cursor replacement.

        Args:
            next_index: Original next zero-based position.
            last: Original last selected saved album.

        Returns:
            Original checkpoint fields and fixed effective write time.
        """
        return {
            "updated_at": NOW.isoformat(),
            "next_alphabetical_index": next_index,
            "last_alphabetical_album_id": last.spotify_id,
            "last_alphabetical_artist": last.artist,
            "last_alphabetical_album": last.album,
        }

    def audit(self, summary: PalaceOfMemorySummary) -> None:
        """Accept original audit after the durable cursor checkpoint.

        Args:
            summary: Original complete outcome.
        """
        self.edge.record("audit", "audit", asdict(summary))


def _run(edge: PalaceObservations, preview: bool) -> object:
    override = "3" if edge.scenario == "override" else None
    if edge.scenario == "invalid-override":
        override = ""
    result = Palace(MemoryPalace(edge)).run("destination", preview, override)
    assert result.added == result.playlist_length_after - result.playlist_length_before
    return asdict(result)


def _outcome(case: dict[str, object]) -> object:
    edge = PalaceObservations(
        cast(str, case["scenario"]), cast(str | None, case["failure"])
    )
    result: dict[str, object] = {}
    try:
        result["result"] = _run(edge, bool(case["preview"]))
    except RuntimeError as exc:
        result.update(error=type(exc).__name__, message=str(exc))
    result["trace"] = edge.trace
    return json.loads(json.dumps(result, default=str))


@pytest.mark.parametrize("case", cases())
def test_injected_palace_matches_original_complete_run(case: dict[str, object]) -> None:
    """Compare complete results and accepted-effect prefixes with the original runner.

    Args:
        case: Original immutable inputs and observed outcome.
    """
    assert _outcome(case) == case["outcome"]


def _recovery_cases() -> list[dict[str, object]]:
    return cast(
        list[dict[str, object]],
        json.loads(FIXTURE.with_name("palace_recovery.json").read_text()),
    )


def _recovery_outcome(failure: str) -> object:
    edge = PalaceObservations("normal", failure)
    outcome: dict[str, object] = {}
    try:
        _run(edge, False)
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    edge.failure = None
    outcome["result"] = _run(edge, False)
    outcome["trace"] = edge.trace
    return json.loads(json.dumps(outcome, default=str))


@pytest.mark.parametrize("case", _recovery_cases())
def test_palace_recovery_retains_original_live_and_checkpoint_authority(
    case: dict[str, object],
) -> None:
    """Retain original resumed cursor positions and suppression of accepted markers.

    Args:
        case: Original immutable accepted-boundary recovery scenario.
    """
    failure = cast(str, case["failure"])
    assert recovery_outcome(failure) == case["outcome"]
    assert _recovery_outcome(failure) == case["outcome"]
