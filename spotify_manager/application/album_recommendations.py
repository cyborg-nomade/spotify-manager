"""Observe Sauvignon track-to-album evidence in original candidate order."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from spotify_manager.domain.album_recommendations import AlbumEvidence
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_recommendations import genuinely_ambiguous
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate


@dataclass(frozen=True)
class AlbumGathering:
    """Observe each original search before combining its album support.

    Args:
        search: Existing ordered eligible album observation boundary.
        progress: Original candidate presenter.
    """

    search: Callable[[FoundArtCandidate], tuple[SpotifyAlbumOption, ...]]
    progress: Callable[[str], None]

    def run(
        self,
        candidates: tuple[FoundArtCandidate, ...],
        excluded: set[AlbumKey],
        existing: set[str],
        maximum: int,
        week: date,
    ) -> tuple[AlbumRecommendation, ...]:
        """Search the original Python-sliced track pool and rank accumulated albums.

        Args:
            candidates: Original ordered ranked track pool.
            excluded: Original heard and previously added album keys.
            existing: Original represented destination album identities.
            maximum: Original slice boundary, including nonpositive helper tolerance.
            week: Original effective listening week.

        Returns:
            Original ranked album recommendations after all observations succeed.

        Raises:
            SauvignonSpotifyError: An existing catalog observation is unusable.
        """
        evidence = AlbumEvidence(excluded, existing)
        considered = candidates[:maximum]
        for index, candidate in enumerate(considered, start=1):
            self.progress(
                f"Resolving album evidence {index}/{len(considered)}: "
                f"{candidate.artist} - {candidate.track}"
            )
            evidence.observe(candidate, self.search(candidate))
        return evidence.ranked(week)


def choose_album(
    recommendation: AlbumRecommendation,
    choice_reader: Callable[[AlbumRecommendation, tuple[SpotifyAlbumOption, ...]], str]
    | None,
    skip_marker: str,
    quit_marker: str,
) -> SpotifyAlbumOption | Literal["skip", "quit"]:
    """Choose automatically unless original visible metadata requires interaction.

    Args:
        recommendation: Original ranked album evidence and ordered preferred editions.
        choice_reader: Original operator interaction, absent for noninteractive runs.
        skip_marker: Original skip response marker.
        quit_marker: Original quit response marker.

    Returns:
        First equivalent edition, selected first matching identity, skip or quit.

    Raises:
        OSError: An injected interaction fails, without translation or retry.
    """
    options = recommendation.options
    if not options:
        return "skip"
    if not genuinely_ambiguous(options):
        return options[0]
    if choice_reader is None:
        return "skip"
    choice = choice_reader(recommendation, options)
    if choice == skip_marker:
        return "skip"
    if choice == quit_marker:
        return "quit"
    for option in options:
        if option.spotify_id == choice:
            return option
    return "skip"
