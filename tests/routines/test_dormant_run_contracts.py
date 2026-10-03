"""Characterize original dormant recovery before extracting its application owner."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import cast

import pytest
from functools import partialmethod
from spotify_manager.infrastructure.legacy.dormant_artists import LegacyDormantRecovery
from spotipy import Spotify

from spotify_manager.routines import blast_from_past as blast
from spotify_manager.routines import blast_from_past_artists as legacy
from spotify_manager.routines import new_kids
from spotify_manager.routines import release_check


@dataclass
class Observations:
    """Record original dormant effects and accepted append failures.

    Args:
        failure: Boundary to fail after recording it.
    """

    failure: str | None = None
    events: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)

    def _record(self, event: str) -> None:
        self.events.append(event)
        if self.failure == event:
            raise RuntimeError(event)

    def candidates(
        self, *args: object, **kwargs: object
    ) -> tuple[legacy.DormantArtist, ...]:
        """Return original alphabetical candidates.

        Args:
            args: Compatibility arguments.
            kwargs: Original selection settings.

        Returns:
            Original ordered history observations.
        """
        self._record("candidates")
        return (legacy.DormantArtist("artist", "Artist", 4),)

    def read(self, *args: object) -> blast.PlaylistState:
        """Return original empty destination.

        Args:
            args: Compatibility arguments.

        Returns:
            Observed membership.
        """
        self._record("read")
        return blast.PlaylistState(0, frozenset())

    def cancel(self) -> bool:
        """Record the original safe cancellation boundary."""
        self._record("cancel")
        return False

    def progress(self, done: int, total: int, text: str) -> None:
        """Record original candidate or completion progress.

        Args:
            done: Proposed additions.
            total: Requested additions.
            text: Original progress message.
        """
        assert total == 1
        self._record(f"progress:{done}:{text}")

    def mapping(
        self, sp: object, artist: legacy.DormantArtist, rank: int, retry: object
    ) -> release_check.SpotifyArtistCandidate:
        """Return an exact original artist mapping.

        Args:
            sp: Caller-owned client.
            artist: Ranked dormant artist.
            rank: Original full candidate position.
            retry: Original retry policy.

        Returns:
            Exact original mapping.
        """
        assert rank == 1 and artist.name == "Artist"
        self._record("mapping")
        return release_check.SpotifyArtistCandidate(
            "artist", "Artist", "uri", 1, 1, 1, True
        )

    def track(self, sp: object, artist_id: str, retry: object) -> new_kids.CatalogTrack:
        """Return an originally liked marker.

        Args:
            sp: Caller-owned client.
            artist_id: Mapped artist identity.
            retry: Original retry policy.

        Returns:
            Original selected marker.
        """
        self._record("track")
        return new_kids.CatalogTrack(
            "track", "spotify:track:track", "Song", 1, 1, artist_id, "Artist", 50
        )

    def append(
        self,
        sp: object,
        playlist: str,
        matches: list[blast.SpotifyTrackMatch],
        retry: object,
        cancel: object,
    ) -> None:
        """Accept all original proposals before an injected ambiguous append failure.

        Args:
            sp: Caller-owned client.
            playlist: Original destination.
            matches: Original converted proposals.
            retry: Original retry policy.
            cancel: Original cancellation callback.
        """
        self.accepted.extend(match.uri for match in matches)
        self._record("append")


def _immediate(operation: Callable[[], object], description: str) -> object:
    return operation()


def _bind(monkeypatch: pytest.MonkeyPatch, effects: Observations) -> None:
    monkeypatch.setattr(legacy, "dormant_artists", effects.candidates)
    monkeypatch.setattr(blast, "load_playlist_state", effects.read)
    monkeypatch.setattr(legacy, "_spotify_artist", effects.mapping)
    monkeypatch.setattr(LegacyDormantRecovery, "track", partialmethod(_track, effects))
    monkeypatch.setattr(blast, "add_spotify_matches", effects.append)


def _run(effects: Observations, preview: bool = False) -> legacy.DormantArtistSummary:
    return legacy.add_dormant_artists_to_blast_from_past(
        cast(Spotify, object()),
        "destination",
        count=1,
        today=date(2026, 9, 25),
        progress_callback=effects.progress,
        cancel_check=effects.cancel,
        retry_call=_immediate,
        dry_run=preview,
    )


EVENTS = [
    "candidates",
    "read",
    "cancel",
    "progress:0:Checking dormant artist Artist",
    "mapping",
    "track",
    "append",
    "progress:1:Dormant-artist recovery complete",
]


@pytest.mark.parametrize("failure", EVENTS)
def test_original_dormant_failure_prefix(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Protect cancellation, interaction and accepted-write failure ordering.

    Args:
        monkeypatch: Original boundary substitutions.
        failure: Original effect at which to fail.
    """
    effects = Observations(failure)
    _bind(monkeypatch, effects)
    with pytest.raises(RuntimeError, match=failure):
        _run(effects)
    assert effects.events == EVENTS[: EVENTS.index(failure) + 1]
    assert effects.accepted == (
        ["spotify:track:track"]
        if EVENTS.index(failure) >= EVENTS.index("append")
        else []
    )


@pytest.mark.parametrize("preview", [False, True])
def test_original_dormant_preview(
    monkeypatch: pytest.MonkeyPatch, preview: bool
) -> None:
    """Protect original added labels in previews while suppressing remote appends.

    Args:
        monkeypatch: Original boundary substitutions.
        preview: Original preview mode.
    """
    effects = Observations()
    _bind(monkeypatch, effects)
    summary = _run(effects, preview)
    assert summary.added == 1
    assert summary.playlist_length_after == int(not preview)
    assert effects.events == (EVENTS[:6] + EVENTS[7:] if preview else EVENTS)
    assert summary.history_years == (2022, 2023, 2024, 2025)


def _track(
    resources: LegacyDormantRecovery,
    effects: Observations,
    artist: str,
) -> new_kids.CatalogTrack:
    return effects.track(resources.spotify, artist, resources.retry)
