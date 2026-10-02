"""Original Something Old result and error contracts without runtime dependencies."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from spotify_manager.application.history_values import ScrobbleHistorySummary
from spotify_manager.domain.catalog import DiscographyRelease
from spotify_manager.domain.golden_oldies import GoldenOldieArtist
from spotify_manager.domain.golden_selection import SelectedTrack
from spotify_manager.domain.golden_selection import SelectionMode
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate


type SummaryAction = Literal["playlist not empty", "cancelled", "would add", "added"]


class SomethingOldError(RuntimeError):
    """Base error for the original Something Old routine."""


class SomethingOldConfigError(SomethingOldError):
    """Original destination playlist configuration is unusable."""


class SomethingOldSpotifyError(SomethingOldError):
    """Original Spotify observations are incomplete or ambiguous."""


@dataclass(frozen=True)
class SomethingOldSummary:
    """Original complete Something Old decision and optional accepted mutation.

    Args:
        generated_at: Original effective UTC timestamp.
        playlist_id: Original destination identity.
        playlist_length_before: Original observed length before selection.
        playlist_length_after: Original observed or proposed final length.
        dry_run: Original preview behavior.
        action: Original completed or cancelled outcome.
        history_refresh: Original optional complete history refresh.
        ranking_preview: Original first ten Golden Oldies ranking facts.
        artist: Original selected history artist, when present.
        spotify_artist: Original accepted Spotify mapping, when present.
        mode: Original accepted selection mode, when present.
        release: Original accepted studio release, when present.
        tracks: Original ordered selected markers.
    """

    generated_at: datetime
    playlist_id: str
    playlist_length_before: int
    playlist_length_after: int
    dry_run: bool
    action: SummaryAction
    history_refresh: ScrobbleHistorySummary | None
    ranking_preview: tuple[GoldenOldieArtist, ...]
    artist: GoldenOldieArtist | None
    spotify_artist: SpotifyArtistCandidate | None
    mode: SelectionMode | None
    release: DiscographyRelease | None
    tracks: tuple[SelectedTrack, ...]
