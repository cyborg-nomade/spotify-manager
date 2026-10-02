"""Independent playlist workflows preserve capacity, previews and effect boundaries."""

from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import date
from datetime import datetime

import pytest

from spotify_manager.application.historical_playlists import AnniversaryPlaylist
from spotify_manager.application.historical_playlists import BlastPlaylist
from spotify_manager.application.historical_playlists import HistoricalPlaylistEffects
from spotify_manager.application.historical_values import BlastFromPastBatch
from spotify_manager.application.historical_values import BlastFromPastCancelledError
from spotify_manager.application.historical_values import BlastFromPastConfigError
from spotify_manager.application.historical_values import DailyMindRadioBatch
from spotify_manager.application.historical_values import PlaylistState
from spotify_manager.application.historical_values import SpotifySelectionResolution
from spotify_manager.application.historical_values import SpotifySelectionResult
from spotify_manager.application.historical_values import SpotifyTrackMatch
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history import ScrobbleSelection


def _selection() -> ScrobbleSelection:
    return ScrobbleSelection(
        date(2020, 1, 1),
        0,
        1,
        1,
        1,
        "top down",
        1,
        Scrobble("Song", "Artist", "Album", 1000),
    )


def _match() -> SpotifyTrackMatch:
    return SpotifyTrackMatch(
        "track", "spotify:track:track", "Song", ("Artist",), "Album", 1, 1.0, 1.0, 50
    )


@dataclass
class PlaylistMemory:
    """Observe workflow boundaries without Spotify or local files.

    Args:
        total: Observed destination size.
        pending: Whether resolution has a pending addition.
        empty: Whether anniversary selection is empty.
        events: Ordered integration calls.
        messages: Presented progress.
        counts: Requested historical selection counts.
        appended: Accepted matches.
        failure: Boundary that raises after observation.
        cancel_at: One-based cancellation check that stops work.
        checks: Cancellation checks observed.
    """

    total: int = 3
    pending: bool = True
    empty: bool = False
    events: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)
    appended: list[SpotifyTrackMatch] = field(default_factory=list)
    failure: str = ""
    cancel_at: int = 0
    checks: int = 0

    def _step(self, name: str) -> None:
        self.events.append(name)
        if self.failure == name:
            raise OSError(name)

    def read(self) -> PlaylistState:
        """Observe existing destination facts.

        Returns:
            Playlist size and membership.
        """
        self._step("read")
        return PlaylistState(self.total, frozenset())

    def resolve(
        self, selections: tuple[ScrobbleSelection, ...], playlist: PlaylistState
    ) -> SpotifySelectionResolution:
        """Observe search and live liked resolution.

        Args:
            selections: Original selected plays.
            playlist: Existing destination facts.

        Returns:
            One added or already-present result.
        """
        self._step("resolve")
        assert playlist.total_items == self.total
        result = SpotifySelectionResult(
            selections[0], _match(), 1, "added" if self.pending else "already present"
        )
        return SpotifySelectionResolution(
            (result,), (_match(),) if self.pending else ()
        )

    def append(self, matches: list[SpotifyTrackMatch]) -> None:
        """Accept the original ordered pending matches.

        Args:
            matches: Tracks to append.
        """
        self._step("append")
        self.appended.extend(matches)

    def cancel(self) -> None:
        """Observe cancellation boundaries.

        Raises:
            BlastFromPastCancelledError: The selected boundary is reached.
        """
        self._step("cancel")
        self.checks += 1
        if self.checks == self.cancel_at:
            raise BlastFromPastCancelledError("cancelled")

    def blast(self, count: int) -> BlastFromPastBatch:
        """Select a fixed Friday batch after recording the requested count.

        Args:
            count: Requested historical date count.

        Returns:
            One selected play and the original batch metadata.
        """
        self._step("select")
        self.counts.append(count)
        return BlastFromPastBatch(
            datetime(2026, 1, 1, tzinfo=UTC), date(2021, 12, 31), 10, (_selection(),)
        )

    def radio(self) -> DailyMindRadioBatch:
        """Select the fixed anniversary batch.

        Returns:
            Populated or empty anniversary selections.
        """
        self._step("select")
        return DailyMindRadioBatch(
            None, (date(2020, 1, 1),), (), () if self.empty else (_selection(),)
        )


def _effects(memory: PlaylistMemory) -> HistoricalPlaylistEffects:
    return HistoricalPlaylistEffects(
        memory.read,
        memory.resolve,
        memory.append,
        memory.cancel,
        memory.messages.append,
    )


def _blast(memory: PlaylistMemory) -> BlastPlaylist:
    return BlastPlaylist(_effects(memory), memory.blast)


def _radio(memory: PlaylistMemory) -> AnniversaryPlaylist:
    return AnniversaryPlaylist(_effects(memory), memory.radio)


@pytest.mark.parametrize(
    "count,maximum,message",
    [
        (1, 4, "not both"),
        (0, None, "Count must"),
        (-1, None, "Count must"),
        (None, 0, "Maximum playlist"),
        (None, -1, "Maximum playlist"),
    ],
)
def test_invalid_blast_request_precedes_every_observation(
    count: int | None, maximum: int | None, message: str
) -> None:
    """Validate explicit configuration before cancellation, presentation or reads.

    Args:
        count: Optional explicit date count.
        maximum: Optional destination capacity.
        message: Original error text.
    """
    memory = PlaylistMemory()
    with pytest.raises(BlastFromPastConfigError, match=message):
        _blast(memory).run("target", count, maximum, False)
    assert not memory.events and not memory.messages


@pytest.mark.parametrize(
    "count,maximum,expected", [(2, None, 2), (None, None, 10), (None, 8, 5)]
)
def test_blast_capacity_determines_selection_count(
    count: int | None, maximum: int | None, expected: int
) -> None:
    """Observe the destination once before applying count or capacity selection.

    Args:
        count: Optional explicit count.
        maximum: Optional destination capacity.
        expected: Effective selection count.
    """
    memory = PlaylistMemory()
    result = _blast(memory).run("target", count, maximum, False)
    assert memory.counts == [expected] and result.requested_count == expected
    assert result.playlist_id == "target" and result.batch is not None
    assert memory.events == ["cancel", "read", "select", "cancel", "resolve", "append"]
    assert result.playlist_length_before == 3 and result.playlist_length_after == 4
    assert result.added == 1 and memory.appended == [_match()]


@pytest.mark.parametrize("total", [3, 4])
def test_blast_full_destination_skips_history_and_matching(total: int) -> None:
    """Capacity is clamped at zero for full or oversized destinations.

    Args:
        total: Observed playlist length.
    """
    memory = PlaylistMemory(total=total)
    result = _blast(memory).run("target", None, 3, False)
    assert memory.events == ["cancel", "read"]
    assert result.batch is None and not result.results
    assert result.requested_count == result.added == 0
    assert result.playlist_length_before == result.playlist_length_after == total


@pytest.mark.parametrize(
    "preview,pending", [(False, False), (True, False), (True, True)]
)
def test_blast_preview_and_empty_resolution_suppress_append(
    preview: bool, pending: bool
) -> None:
    """Only real pending additions affect the projected destination size.

    Args:
        preview: Whether remote writes are suppressed.
        pending: Whether resolution includes an addition.
    """
    memory = PlaylistMemory(pending=pending)
    result = _blast(memory).run("target", 1, None, preview)
    assert memory.events == ["cancel", "read", "select", "cancel", "resolve"]
    assert result.playlist_length_after == 3 and result.added == int(pending)
    assert memory.messages == ["Loading the Spotify playlist"]


def test_radio_empty_selection_retains_nullable_lengths() -> None:
    """Check cancellation after selection but skip every Spotify observation."""
    memory = PlaylistMemory(empty=True)
    result = _radio(memory).run("target", False)
    assert memory.events == ["cancel", "select", "cancel"]
    assert (
        result.playlist_length_before is None and result.playlist_length_after is None
    )
    assert result.added == 0 and not result.results and not memory.messages


@pytest.mark.parametrize(
    "preview,pending", [(False, True), (False, False), (True, True)]
)
def test_radio_selection_precedes_destination_observation(
    preview: bool, pending: bool
) -> None:
    """Maintain radio's distinct preparation order and preview result actions.

    Args:
        preview: Whether remote writes are suppressed.
        pending: Whether resolution includes an addition.
    """
    memory = PlaylistMemory(pending=pending)
    result = _radio(memory).run("target", preview)
    expected = ["cancel", "select", "cancel", "read", "resolve"]
    added = pending and not preview
    if added:
        expected.append("append")
    assert memory.events == expected and result.playlist_id == "target"
    assert (
        result.playlist_length_before == 3
        and result.playlist_length_after == 3 + int(added)
    )
    assert result.added == int(pending)
    assert ("Adding 1 tracks to Spotify" in memory.messages) is added


@pytest.mark.parametrize("check", [1, 2])
@pytest.mark.parametrize("radio", [False, True])
def test_cancellation_stops_at_the_original_preparation_boundary(
    check: int, radio: bool
) -> None:
    """Prevent matching and append when either routine preparation check cancels.

    Args:
        check: One-based cancellation check.
        radio: Select the anniversary routine.
    """
    memory = PlaylistMemory(cancel_at=check)
    with pytest.raises(BlastFromPastCancelledError):
        if radio:
            _radio(memory).run("target", False)
        else:
            _blast(memory).run("target", 1, None, False)
    assert memory.checks == check and memory.events[-1] == "cancel"
    assert "resolve" not in memory.events and not memory.appended


@pytest.mark.parametrize("failure", ["read", "select", "resolve", "append"])
@pytest.mark.parametrize("radio", [False, True])
def test_observation_and_mutation_failures_propagate(failure: str, radio: bool) -> None:
    """Retain the original exception and suppress later observations or writes.

    Args:
        failure: Selected failing boundary.
        radio: Select the anniversary routine.
    """
    memory = PlaylistMemory(failure=failure)
    with pytest.raises(OSError, match=failure):
        if radio:
            _radio(memory).run("target", False)
        else:
            _blast(memory).run("target", 1, None, False)
    assert memory.events[-1] == failure and not memory.appended
