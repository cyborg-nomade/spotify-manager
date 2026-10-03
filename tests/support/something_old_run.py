"""Capture complete original Something Old decisions and accepted-effect prefixes."""

import json
from contextlib import ExitStack
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from functools import partialmethod
from pathlib import Path
from typing import cast
from unittest.mock import patch

from spotipy import Spotify

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.routines import something_old as legacy
from tests.support.golden_oldies import plays
from tests.support.history_dependencies import LegacySomethingOld
from tests.support.history_dependencies import something_old_history
from tests.support.queue_neighbors import NOW


FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures/refactor/something_old_run.json"
)
ARTIST = legacy.SpotifyArtistCandidate(
    "artist", "Artist", "spotify:artist:artist", 10, 20, 1
)
TRACK = legacy.SelectedTrack(
    "track", "spotify:track:track", "Track", "Album", ("Artist",), "original source", 5
)
RELEASE = DiscographyRelease(
    "release",
    "spotify:album:release",
    "Release",
    "Album",
    "2020",
    "2020",
    3,
    "artist",
    "Artist",
    "release",
    False,
    True,
    0,
)


@dataclass
class OldObservations:
    """Observe original stages with explicit typed history, choices and effects.

    Args:
        scenario: Original configured selection or early-exit scenario.
        failure: Optional accepted boundary that raises.
        trace: Original ordered stage observations.
    """

    scenario: str
    failure: str | None = None
    trace: list[list[object]] = field(default_factory=list)

    def record(self, effect: str, *details: object) -> None:
        """Observe an original boundary before its optional configured failure.

        Args:
            effect: Original observed boundary.
            details: Original boundary arguments.

        Raises:
            RuntimeError: The configured accepted boundary fails.
        """
        self.trace.append([effect, *details])
        count = sum(row[0] == effect for row in self.trace)
        if self.failure in {effect, f"{effect}:{count}"}:
            raise RuntimeError(effect)

    def playlist(
        self,
        spotify: Spotify,
        playlist: str,
        retry: legacy.RetryCall,
        description: str,
    ) -> PlaylistState:
        """Observe initial membership or the original pre-write recheck.

        Args:
            spotify: Original client boundary.
            playlist: Original destination identity.
            retry: Original retry boundary.
            description: Original read-only retry description.

        Returns:
            Original configured playlist size.
        """
        self.record("playlist", playlist, description)
        changed = self.scenario == "changed" and "rechecking" in description
        return PlaylistState(
            1 if changed or self.scenario == "nonempty" else 0, frozenset()
        )

    def history(
        self, reader: legacy.LastFmReader, **options: object
    ) -> ScrobbleHistorySummary:
        """Observe original history refresh parameters before ranking.

        Args:
            reader: Original caller-owned Last.fm reader.
            options: Original typed refresh keyword boundary.

        Returns:
            Original complete refresh summary.
        """
        preview = bool(options["dry_run"])
        now = cast(datetime, options["now"])
        self.record("history", options["expected_username"], preview, now.isoformat())
        history = () if self.scenario == "no-history" else plays("descending")
        return ScrobbleHistorySummary(
            now, "listener", history, len(history), 0, 2, preview, False, None
        )

    def resolve(
        self,
        spotify: Spotify,
        artist: str,
        reader: legacy.ArtistSearchChoiceReader | None,
        retry: legacy.RetryCall,
    ) -> legacy.SpotifyArtistCandidate | None:
        """Observe original exact-artist resolution and configured cancellation.

        Args:
            spotify: Original client boundary.
            artist: Original selected Golden Oldies spelling.
            reader: Original optional interaction adapter.
            retry: Original retry boundary.

        Returns:
            Original fixed mapping or artist-choice cancellation.
        """
        self.record("resolve", artist, reader is None)
        return None if self.scenario == "quit-artist" else ARTIST

    def mode(
        self,
        artist: legacy.GoldenOldieArtist,
        spotify: legacy.SpotifyArtistCandidate,
    ) -> str:
        """Observe original mode interaction after accepting an artist.

        Args:
            artist: Original selected history artist.
            spotify: Original accepted Spotify mapping.

        Returns:
            Original configured mode or quit choice.
        """
        self.record("mode", artist.artist, spotify.spotify_id)
        if self.scenario == "quit-mode":
            return "quit"
        if self.scenario == "quit-album":
            return "album"
        if self.scenario in {"lastfm_top_tracks", "album", "invalid-mode"}:
            return self.scenario
        return "spotify_top_tracks"

    def lastfm_tracks(
        self,
        spotify: Spotify,
        artist: legacy.GoldenOldieArtist,
        retry: legacy.RetryCall,
    ) -> tuple[legacy.SelectedTrack, ...]:
        """Observe the original Last.fm track selection seam.

        Args:
            spotify: Original client boundary.
            artist: Original selected history artist.
            retry: Original retry boundary.

        Returns:
            Original selected markers.
        """
        self.record("lastfm-tracks", artist.artist)
        return (TRACK,)

    def spotify_tracks(
        self,
        spotify: Spotify,
        artist: legacy.SpotifyArtistCandidate,
        retry: legacy.RetryCall,
    ) -> tuple[legacy.SelectedTrack, ...]:
        """Observe the original Spotify track selection seam.

        Args:
            spotify: Original client boundary.
            artist: Original accepted Spotify artist.
            retry: Original retry boundary.

        Returns:
            Original selected markers.
        """
        self.record("spotify-tracks", artist.spotify_id)
        return (TRACK,)

    def album_tracks(
        self,
        spotify: Spotify,
        artist: legacy.GoldenOldieArtist,
        mapped: legacy.SpotifyArtistCandidate,
        reader: legacy.AlbumChoiceReader,
        retry: legacy.RetryCall,
    ) -> tuple[DiscographyRelease | None, tuple[legacy.SelectedTrack, ...]]:
        """Observe original album interaction and its cancellation result.

        Args:
            spotify: Original client boundary.
            artist: Original selected history artist.
            mapped: Original accepted Spotify mapping.
            reader: Original album-choice presenter.
            retry: Original retry boundary.

        Returns:
            Original selected release/markers or cancellation.
        """
        self.record("album-tracks", artist.artist, mapped.spotify_id)
        return (None, ()) if self.scenario == "quit-album" else (RELEASE, (TRACK,))

    def album_choice(
        self,
        artist: legacy.GoldenOldieArtist,
        releases: tuple[DiscographyRelease, ...],
    ) -> str:
        """Supply a typed unused presenter through the original required boundary.

        Args:
            artist: Original selected history artist.
            releases: Original observed studio releases.

        Returns:
            Original fixed release identity.
        """
        return RELEASE.spotify_id

    def append(
        self, spotify: Spotify, playlist: str, tracks: tuple[legacy.SelectedTrack, ...]
    ) -> None:
        """Accept the original complete selection append.

        Args:
            spotify: Original client boundary.
            playlist: Original destination identity.
            tracks: Original selected markers in source order.
        """
        self.record("append", playlist, [track.uri for track in tracks])

    def audit(self, summary: legacy.SomethingOldSummary, path: Path) -> None:
        """Accept the original real-run completion record.

        Args:
            summary: Original completed summary.
            path: Original audit location.
        """
        self.record("audit", asdict(summary))

    def progress(self, message: str) -> None:
        """Observe original optional progress text.

        Args:
            message: Original stage text.
        """
        self.record("progress", message)


def _patches(edge: OldObservations) -> tuple[tuple[object, str, object], ...]:
    return (
        (legacy, "_load_playlist_state", edge.playlist),
        (
            LegacySomethingOld,
            "history",
            partialmethod(something_old_history, edge.history),
        ),
        (legacy, "resolve_spotify_artist", edge.resolve),
        (legacy, "select_lastfm_top_tracks", edge.lastfm_tracks),
        (legacy, "select_spotify_top_tracks", edge.spotify_tracks),
        (legacy, "select_album_tracks", edge.album_tracks),
        (legacy, "_add_tracks", edge.append),
        (legacy, "_append_log", edge.audit),
    )


def _run(edge: OldObservations, preview: bool) -> object:
    with ExitStack() as stack:
        for module, name, callback in _patches(edge):
            stack.enter_context(patch.object(module, name, callback))
        result = legacy.run_something_old(
            cast(Spotify, edge),
            cast(legacy.LastFmReader, edge),
            "destination",
            expected_username="listener",
            mode_reader=edge.mode,
            album_choice_reader=edge.album_choice,
            dry_run=preview,
            now=NOW,
            progress_callback=edge.progress,
        )
    return asdict(result)


def original_outcome(scenario: str, preview: bool, failure: str | None) -> object:
    """Observe the original complete workflow before coordinator extraction.

    Args:
        scenario: Original mode, early exit or membership-change behavior.
        preview: Original preview behavior.
        failure: Optional accepted boundary that raises.

    Returns:
        JSON-compatible original result/error and effect prefix.
    """
    edge = OldObservations(scenario, failure)
    outcome: dict[str, object] = {}
    try:
        outcome["result"] = _run(edge, preview)
    except RuntimeError as exc:
        outcome.update(error=type(exc).__name__, message=str(exc))
    outcome["trace"] = edge.trace
    return json.loads(json.dumps(outcome, default=str))


def cases() -> list[tuple[str, dict[str, object]]]:
    """Read immutable original Something Old complete-run observations.

    Returns:
        Named original inputs and complete result/effect evidence.
    """
    raw = cast(dict[str, dict[str, object]], json.loads(FIXTURE.read_text()))
    return list(raw.items())
