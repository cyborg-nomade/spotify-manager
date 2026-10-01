"""Typed Queue fill requests, gathered facts and original result contracts."""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.discovery import CatalogTrack
from spotify_manager.domain.queue_values import ArtistHistory
from spotify_manager.domain.queue_values import ArtistRecommendation


type FillAction = Literal[
    "added",
    "would add",
    "already represented",
    "no Spotify match",
    "no unliked top track",
    "skipped",
]


@dataclass(frozen=True)
class FillResult:
    """Original Spotify resolution outcome for one artist recommendation.

    Args:
        recommendation: Original Last.fm candidate.
        spotify_artist: Original accepted Spotify mapping, when present.
        track: Original selected marker, when present.
        action: Original observed or proposed outcome.
        followed: Whether following was performed or would be needed.
    """

    recommendation: ArtistRecommendation
    spotify_artist: SpotifyArtistCandidate | None
    track: CatalogTrack | None
    action: FillAction
    followed: bool = False


@dataclass(frozen=True)
class FillSummary:
    """Original outcome of one Last.fm-driven Queue fill.

    Args:
        week_start: Original effective listening week.
        requested_count: Original effective requested additions.
        history_artists: Original distinct history artists.
        history_scrobbles: Original refreshed play count.
        live_scrobbles_added: Original live history additions.
        seed_count: Original selected seed count.
        candidate_count: Original gathered recommendation count.
        playlist_length_before: Original observed Queue length.
        playlist_length_after: Original actual length or preview length.
        paused: Whether the original quit choice was received.
        dry_run: Original preview mode.
        results: Original ordered outcomes, including rejections.
    """

    week_start: date
    requested_count: int
    history_artists: int
    history_scrobbles: int
    live_scrobbles_added: int
    seed_count: int
    candidate_count: int
    playlist_length_before: int
    playlist_length_after: int
    paused: bool
    dry_run: bool
    results: tuple[FillResult, ...]

    @property
    def selected(self) -> int:
        """Count original actual or proposed Queue additions.

        Returns:
            Number of added or would-add outcomes.
        """
        return sum(result.action in {"added", "would add"} for result in self.results)


@dataclass(frozen=True)
class QueueFillRequest:
    """Original mutually exclusive Queue fill limits and preview behavior.

    Args:
        count: Original optional requested number of additions.
        maximum_length: Original optional maximum Queue length.
        seed_count: Original requested weekly seeds.
        preview: Original preview behavior.
    """

    count: int | None
    maximum_length: int | None
    seed_count: int
    preview: bool


@dataclass(frozen=True)
class QueueFillFacts:
    """Gathered history and Queue facts shared by the fill's meaningful stages.

    Args:
        week: Original effective listening week.
        history: Original aggregated history facts.
        plays: Original refreshed play count.
        live_added: Original live history additions.
        before: Original observed Queue length.
        requested: Original effective requested additions.
    """

    week: date
    history: tuple[ArtistHistory, ...]
    plays: int
    live_added: int
    before: int
    requested: int
