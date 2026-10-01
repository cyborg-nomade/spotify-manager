"""Resolve Queue candidates and preserve accepted mapping, follow and append order."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from typing import Literal

from spotify_manager.application.queue_fill_effects import QueueFillEffects
from spotify_manager.application.queue_fill_effects import QueueFillState
from spotify_manager.application.queue_fill_values import FillResult
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.queue_fill import first_unliked
from spotify_manager.domain.queue_values import ArtistRecommendation


@dataclass
class QueueFillCandidates:
    """Process ordered candidates with separate durable mapping and playlist effects.

    Args:
        effects: Original read, interaction and accepted-effect boundaries.
        access: Original checkpoint writer.
        state: Caller-owned complete original state.
        mappings: Caller-owned original artist mappings.
        represented: Original represented artist set updated after additions.
        preview: Original preview behavior.
        results: Ordered completed outcomes, including rejections.
        selected: Original actual or proposed addition count.
        paused: Whether the original quit choice was received.
        multiplier: Original candidate examination multiplier.
        top_track_limit: Original top-track window.
    """

    effects: QueueFillEffects
    access: QueueFillState
    state: dict[str, object]
    mappings: dict[str, object]
    represented: set[str]
    preview: bool
    results: list[FillResult] = field(default_factory=list)
    selected: int = 0
    paused: bool = False
    multiplier: int = 10
    top_track_limit: int = 10

    def run(self, candidates: tuple[ArtistRecommendation, ...], requested: int) -> None:
        """Process the original bounded pool until the requested additions or quit.

        Args:
            candidates: Original weekly ordering.
            requested: Original requested additions.
        """
        maximum = min(len(candidates), max(requested, requested * self.multiplier))
        for index, candidate in enumerate(candidates[:maximum], start=1):
            if self.selected >= requested:
                break
            self.effects.progress(index - 1, maximum, f"Resolving {candidate.artist}")
            outcome = self._process(candidate)
            if outcome == "quit":
                self.paused = True
                break
            self._complete(outcome)

    def _mapping(
        self,
        candidate: ArtistRecommendation,
    ) -> SpotifyArtistCandidate | FillResult | Literal["quit"]:
        artist = self.effects.decode_mapping(self.mappings.get(candidate.key))
        if artist is not None:
            return artist
        resolved = self.effects.resolve(candidate)
        if resolved == "quit":
            return "quit"
        if resolved == "skip":
            return FillResult(candidate, None, None, "skipped")
        if not isinstance(resolved, SpotifyArtistCandidate):
            return FillResult(candidate, None, None, "no Spotify match")
        self.mappings[candidate.key] = asdict(resolved)
        self.access.save(self.state)
        return resolved

    def _process(self, candidate: ArtistRecommendation) -> FillResult | Literal["quit"]:
        mapped = self._mapping(candidate)
        if not isinstance(mapped, SpotifyArtistCandidate):
            return mapped
        if mapped.spotify_id in self.represented:
            return FillResult(candidate, mapped, None, "already represented")
        tracks = self.effects.top_tracks(mapped)[: self.top_track_limit]
        target = first_unliked(tracks, self.effects.liked(tracks))
        if target is None:
            return FillResult(candidate, mapped, None, "no unliked top track")
        followed_now = not self.effects.following(mapped)
        self._append(mapped, target, followed_now)
        return FillResult(
            candidate,
            mapped,
            target,
            "would add" if self.preview else "added",
            followed=followed_now,
        )

    def _append(
        self,
        artist: SpotifyArtistCandidate,
        target: CatalogTrack,
        follow: bool,
    ) -> None:
        if self.preview:
            return
        if follow:
            self.effects.follow(artist)
            self.effects.persist_followed(artist)
        self.effects.append(artist, target)

    def _complete(self, result: FillResult) -> None:
        self.results.append(result)
        selected = result.action in {"added", "would add"}
        if selected:
            assert result.spotify_artist is not None
            self.represented.add(result.spotify_artist.spotify_id)
            self.selected += 1
        self.effects.audit(result, self.preview, selected)
        if selected:
            self.effects.present(result, self.preview)
