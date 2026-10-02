"""Protect clock boundaries, batching and original exception scopes."""

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime

import pytest

from spotify_manager.application.legacy_library_effects import PlaylistClock
from spotify_manager.application.legacy_library_refresh import append_tracks
from spotify_manager.application.legacy_library_refresh import playlist
from spotify_manager.infrastructure.legacy_library_errors import LegacyFailure
from spotify_manager.models.tracks import SimplifiedTrack


@dataclass
class Effects:
    """Observe explicit presentation, accepted requests and independent clocks.

    Args:
        times: Original independent clock observations.
        output: Original visible values.
        additions: Original ordered mutations.
    """

    times: list[datetime] = field(default_factory=list)
    output: list[tuple[object, ...]] = field(default_factory=list)
    additions: list[tuple[str, list[str]]] = field(default_factory=list)

    def echo(self, *values: object) -> None:
        """Observe original positional presentation.

        Args:
            values: Original displayed values.
        """
        self.output.append(values)

    def append(self, identifier: str, uris: list[str]) -> None:
        """Accept the original ordered addition.

        Args:
            identifier: Original playlist identity.
            uris: Original track order.
        """
        self.additions.append((identifier, uris.copy()))

    def now(self) -> datetime:
        """Read the next independent clock observation.

        Returns:
            Original observed local time.
        """
        return self.times.pop(0)

    def create(self, name: str) -> object:
        """Accept the original named playlist.

        Args:
            name: Original separately observed year/month name.

        Returns:
            Original raw creation response.
        """
        self.output.append(("created", name))
        return {"id": "playlist"}


@pytest.mark.parametrize(
    "size,expected", [(0, [0]), (100, [100]), (101, [100, 1]), (205, [100, 100, 5])]
)
def test_original_application_batches(size: int, expected: list[int]) -> None:
    """Retain all ordered additions including an empty request.

    Args:
        size: Original raw track count.
        expected: Original request sizes.
    """
    effects = Effects()
    tracks = []
    for index in range(size):
        tracks.append(
            SimplifiedTrack(disc_number=1, track_number=index, uri=str(index))
        )
    append_tracks(tracks, "playlist", effects.append, effects.append, effects.echo)
    assert [len(uris) for _, uris in effects.additions] == expected
    assert effects.output == [("Appending tracks to playlist...",), ("Done!",)]


@pytest.mark.parametrize(
    "condition,selected,expected", [(10, 9, "2025.9"), (9, 10, "2025.010")]
)
def test_original_independent_playlist_clocks(
    condition: int, selected: int, expected: str
) -> None:
    """Preserve separate clock observations across a month/year boundary.

    Args:
        condition: Original month observed by the formatting condition.
        selected: Original month observed by the selected expression.
        expected: Original resulting name.
    """
    effects = Effects(
        times=[
            datetime(2025, 12, 31),
            datetime(2026, condition, 1),
            datetime(2026, selected, 1),
        ]
    )
    assert (
        playlist(PlaylistClock(effects.now, effects.create), effects.echo) == "playlist"
    )
    assert effects.output == [
        ("Creating playlist...",),
        (f"Playlist name: {expected}",),
        ("created", expected),
        ("Done!",),
    ]
    assert effects.times == []


def test_failure_scope_preserves_process_control() -> None:
    """Propagate process control without translating it to a legacy fallback."""
    effects = Effects()
    with pytest.raises(SystemExit), LegacyFailure(effects.echo):
        raise SystemExit(1)
    assert effects.output == []
