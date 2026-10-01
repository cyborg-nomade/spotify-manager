"""Exercise Something Old against typed dependencies and frozen original traces."""

import json
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import pytest

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.something_old_run import SomethingOld
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_oldies import rank_golden_oldies
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from tests.support.golden_oldies import plays
from tests.support.queue_neighbors import NOW
from tests.support.something_old_run import ARTIST
from tests.support.something_old_run import RELEASE
from tests.support.something_old_run import TRACK
from tests.support.something_old_run import OldObservations
from tests.support.something_old_run import cases


@dataclass(frozen=True)
class MemoryOld:
    """Supply typed history and choices without SDK, files or startup.

    Args:
        edge: Original scenario and accepted-boundary observations.
    """

    edge: OldObservations

    def clock(self) -> datetime:
        """Return the fixed original timestamp.

        Returns:
            Original effective time.
        """
        return NOW

    def progress(self, message: str) -> None:
        """Observe original progress.

        Args:
            message: Original visible stage.
        """
        self.edge.record("progress", message)

    def playlist_length(self, recheck: bool) -> int:
        """Supply original initial or changed membership.

        Args:
            recheck: Whether this is the final authority check.

        Returns:
            Original configured playlist size.
        """
        description = (
            "rechecking Something Old before adding"
            if recheck
            else "checking whether Something Old is empty"
        )
        self.edge.record("playlist", "destination", description)
        changed = recheck and self.edge.scenario == "changed"
        return int(changed or self.edge.scenario == "nonempty")

    def history(self, now: datetime, preview: bool) -> ScrobbleHistorySummary:
        """Supply original complete history refresh facts.

        Args:
            now: Effective time.
            preview: Original history preview behavior.

        Returns:
            Original refresh summary.
        """
        self.edge.record("history", "listener", preview, now.isoformat())
        history = () if self.edge.scenario == "no-history" else plays("descending")
        return ScrobbleHistorySummary(
            now, "listener", history, len(history), 0, 2, preview, False, None
        )

    def ranking(self, history: tuple[Scrobble, ...]) -> tuple[GoldenOldieArtist, ...]:
        """Apply the pure Golden Oldies rules.

        Args:
            history: Original refreshed plays.

        Returns:
            Original oldest-first ranking.
        """
        return rank_golden_oldies(history)

    def resolve(self, artist: GoldenOldieArtist) -> SpotifyArtistCandidate | None:
        """Supply the original artist mapping or cancellation.

        Args:
            artist: Selected history artist.

        Returns:
            Fixed mapping or cancellation.
        """
        self.edge.record("resolve", artist.artist, True)
        return None if self.edge.scenario == "quit-artist" else ARTIST

    def mode(self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate) -> str:
        """Supply original mode interaction.

        Args:
            artist: Selected history artist.
            mapped: Accepted Spotify artist.

        Returns:
            Configured original choice.
        """
        return self.edge.mode(artist, mapped)

    def lastfm_tracks(self, artist: GoldenOldieArtist) -> tuple[SelectedTrack, ...]:
        """Supply original most-scrobbled markers.

        Args:
            artist: Selected history artist.

        Returns:
            Original selected markers.
        """
        self.edge.record("lastfm-tracks", artist.artist)
        return (TRACK,)

    def spotify_tracks(
        self, artist: SpotifyArtistCandidate
    ) -> tuple[SelectedTrack, ...]:
        """Supply original popular markers.

        Args:
            artist: Accepted Spotify artist.

        Returns:
            Original selected markers.
        """
        self.edge.record("spotify-tracks", artist.spotify_id)
        return (TRACK,)

    def album_tracks(
        self, artist: GoldenOldieArtist, mapped: SpotifyArtistCandidate
    ) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
        """Supply original release choice or cancellation.

        Args:
            artist: Selected history artist.
            mapped: Accepted Spotify artist.

        Returns:
            Original selected release and tracks.
        """
        self.edge.record("album-tracks", artist.artist, mapped.spotify_id)
        if self.edge.scenario == "quit-album":
            return None, ()
        return RELEASE, (TRACK,)

    def append(self, tracks: tuple[SelectedTrack, ...]) -> None:
        """Observe accepted append in source order.

        Args:
            tracks: Selected markers.
        """
        self.edge.record("append", "destination", [track.uri for track in tracks])

    def audit(self, summary: SomethingOldSummary) -> None:
        """Observe accepted completion audit.

        Args:
            summary: Complete selected outcome.
        """
        self.edge.record("audit", asdict(summary))


def _outcome(case: dict[str, object]) -> object:
    edge = OldObservations(
        cast(str, case["scenario"]), cast(str | None, case["failure"])
    )
    outcome: dict[str, object] = {}
    try:
        result = SomethingOld(MemoryOld(edge)).run("destination", bool(case["preview"]))
        outcome["result"] = asdict(result)
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome["trace"] = edge.trace
    return json.loads(json.dumps(outcome, default=str))


@pytest.mark.parametrize("name,case", cases(), ids=[name for name, _case in cases()])
def test_something_old_original_workflow(name: str, case: dict[str, object]) -> None:
    """Compare the injected workflow with immutable original complete traces.

    Args:
        name: Original scenario identity.
        case: Original inputs and result/effect prefix.
    """
    assert name
    assert _outcome(case) == case["outcome"]
