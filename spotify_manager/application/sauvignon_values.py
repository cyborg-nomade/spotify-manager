"""Stable Sauvignon recommendation errors independent of clients and storage."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime

from spotify_manager.domain.album_selection import SauvignonResult


class SauvignonError(RuntimeError):
    """Base error for the original Sauvignon recommendation workflow."""


class SauvignonConfigError(SauvignonError):
    """Original missing-setting or invalid numeric-request error."""


class SauvignonStateError(SauvignonError):
    """Original unreadable or unwritable durable recommendation-data error."""


class SauvignonSpotifyError(SauvignonError):
    """Original incomplete or unusable catalog or playlist observation error."""


@dataclass(frozen=True)
class SauvignonSummary:
    """Outcome of one Last.fm-driven Sauvignon fill.

    Args:
        generated_at: Effective UTC time.
        week_start: Original listening week.
        playlist_id: Original destination.
        requested_count: Requested additions after capacity calculation.
        history_albums: Distinct valid heard albums.
        history_scrobbles: Canonical plays observed.
        live_scrobbles_added: Newly accepted live plays.
        seed_count: Selected seeds.
        track_candidate_count: Ranked track evidence count.
        album_candidate_count: Ranked album evidence count.
        playlist_length_before: Initial observed length.
        playlist_length_after: Initial length plus accepted additions.
        paused: Original quit outcome.
        dry_run: Original preview mode.
        results: Original ordered outcomes.
    """

    generated_at: datetime
    week_start: date
    playlist_id: str
    requested_count: int
    history_albums: int
    history_scrobbles: int
    live_scrobbles_added: int
    seed_count: int
    track_candidate_count: int
    album_candidate_count: int
    playlist_length_before: int
    playlist_length_after: int
    paused: bool
    dry_run: bool
    results: tuple[SauvignonResult, ...]

    @property
    def selected(self) -> int:
        """Count original proposed or completed additions.

        Returns:
            Number of added or would-add outcomes.
        """
        return sum(result.action in {"added", "would add"} for result in self.results)
