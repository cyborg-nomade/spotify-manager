"""Coordinate Something Old's empty-slot authority, choices and ordered append."""

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.application.something_old_effects import SomethingOldEffects
from spotify_manager.application.something_old_values import SomethingOldError
from spotify_manager.application.something_old_values import SomethingOldSummary
from spotify_manager.application.something_old_values import SummaryAction
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SelectionMode
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate


@dataclass(frozen=True)
class _OldFacts:
    """Retain original gathered history and ranking for meaningful selection stages.

    Args:
        now: Original effective timestamp.
        playlist: Original destination identity.
        preview: Original preview behavior.
        history: Original complete history refresh summary.
        ranking: Original nonempty ordered Golden Oldies facts.
    """

    now: datetime
    playlist: str
    preview: bool
    history: ScrobbleHistorySummary
    ranking: tuple[GoldenOldieArtist, ...]


def _summary(
    facts: _OldFacts,
    action: SummaryAction,
    mapped: SpotifyArtistCandidate | None = None,
    mode: SelectionMode | None = None,
    release: DiscographyRelease | None = None,
    tracks: tuple[SelectedTrack, ...] = (),
) -> SomethingOldSummary:
    return SomethingOldSummary(
        generated_at=facts.now,
        playlist_id=facts.playlist,
        playlist_length_before=0,
        playlist_length_after=0 if facts.preview else len(tracks),
        dry_run=facts.preview,
        action=action,
        history_refresh=facts.history,
        ranking_preview=facts.ranking[:10],
        artist=facts.ranking[0],
        spotify_artist=mapped,
        mode=mode,
        release=release,
        tracks=tracks,
    )


def _nonempty(
    now: datetime, playlist: str, size: int, preview: bool
) -> SomethingOldSummary:
    return SomethingOldSummary(
        now,
        playlist,
        size,
        size,
        preview,
        "playlist not empty",
        None,
        (),
        None,
        None,
        None,
        None,
        (),
    )


@dataclass(frozen=True)
class SomethingOld:
    """Gather oldest-artist facts and preserve cautious empty-playlist execution.

    Args:
        effects: Original caller-owned observations, choices and accepted effects.
        minimum_plays: Original configured eligibility threshold for error text.
    """

    effects: SomethingOldEffects
    minimum_plays: int = 50

    def run(self, playlist: str, preview: bool) -> SomethingOldSummary:
        """Refresh and select only after the original destination-empty check.

        Args:
            playlist: Original destination identity.
            preview: Original preview behavior.

        Returns:
            Original complete selected, cancelled or nonempty outcome.

        Raises:
            SomethingOldError: Original history has no eligible artists.
            SomethingOldSpotifyError: Original catalog or interaction is unusable.
        """
        now = self.effects.clock()
        self.effects.progress("Checking whether Something Old is empty")
        size = self.effects.playlist_length(False)
        if size:
            return _nonempty(now, playlist, size, preview)
        history = self.effects.history(now, preview)
        self.effects.progress("Calculating Golden Oldies average scrobble dates")
        ranking = self.effects.ranking(history.history)
        if not ranking:
            raise SomethingOldError(
                f"No artists have at least {self.minimum_plays} scrobbles."
            )
        facts = _OldFacts(now, playlist, preview, history, ranking)
        mapped = self.effects.resolve(ranking[0])
        if mapped is None:
            return _summary(facts, "cancelled")
        return self._selection(facts, mapped)

    def _selection(
        self, facts: _OldFacts, mapped: SpotifyArtistCandidate
    ) -> SomethingOldSummary:
        artist = facts.ranking[0]
        raw_mode = self.effects.mode(artist, mapped)
        if raw_mode == "quit":
            return _summary(facts, "cancelled", mapped)
        if raw_mode not in {"lastfm_top_tracks", "spotify_top_tracks", "album"}:
            raise SomethingOldError("The Something Old selection mode is invalid.")
        mode = cast(SelectionMode, raw_mode)
        self.effects.progress(f"Preparing {artist.artist}'s {mode.replace('_', ' ')}")
        release, tracks = self._tracks(mode, artist, mapped)
        if mode == "album" and release is None:
            return _summary(facts, "cancelled", mapped, mode)
        self._append(tracks, facts.preview)
        summary = _summary(
            facts,
            "would add" if facts.preview else "added",
            mapped,
            mode,
            release,
            tracks,
        )
        if not facts.preview:
            self.effects.audit(summary)
        return summary

    def _tracks(
        self,
        mode: SelectionMode,
        artist: GoldenOldieArtist,
        mapped: SpotifyArtistCandidate,
    ) -> tuple[DiscographyRelease | None, tuple[SelectedTrack, ...]]:
        if mode == "lastfm_top_tracks":
            return None, self.effects.lastfm_tracks(artist)
        if mode == "spotify_top_tracks":
            return None, self.effects.spotify_tracks(mapped)
        return self.effects.album_tracks(artist, mapped)

    def _append(self, tracks: tuple[SelectedTrack, ...], preview: bool) -> None:
        if preview:
            return
        self.effects.progress("Rechecking the empty playlist before adding")
        if self.effects.playlist_length(True):
            raise SomethingOldError(
                "Something Old changed while the selection was being prepared; "
                "nothing was added."
            )
        self.effects.append(tracks)
