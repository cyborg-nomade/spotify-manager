"""Observe Sauvignon track-to-album evidence in original candidate order."""

from dataclasses import dataclass
from datetime import date
from typing import Literal
from typing import Protocol

from spotify_manager.application.manual_album_matching import ManualAlbumMatching
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.domain.album_recommendations import AlbumEvidence
from spotify_manager.domain.album_recommendations import AlbumKey
from spotify_manager.domain.album_recommendations import AlbumRecommendation
from spotify_manager.domain.album_recommendations import SpotifyAlbumOption
from spotify_manager.domain.album_recommendations import genuinely_ambiguous
from spotify_manager.domain.album_recommendations import manual_album_option
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.recommendation_candidates import FoundArtCandidate


class AlbumChoices(Protocol):
    """Read an operator's choice between distinct album editions."""

    async def choose_album(
        self,
        recommendation: AlbumRecommendation,
        options: tuple[SpotifyAlbumOption, ...],
        /,
    ) -> str:
        """Choose an edition or return the original skip/quit marker.

        Args:
            recommendation: Ranked recommendation being resolved.
            options: Ordered candidate editions.

        Returns:
            Original selected identity or control response.
        """
        ...


class AlbumSearch(Protocol):
    """Observe eligible album editions for one ranked track candidate."""

    async def search(
        self, candidate: FoundArtCandidate
    ) -> tuple[SpotifyAlbumOption, ...]:
        """Read candidate editions through the original catalog boundary.

        Args:
            candidate: Ranked track evidence.

        Returns:
            Eligible editions in original search order.
        """


@dataclass(frozen=True)
class AlbumGathering:
    """Observe each original search before combining its album support.

    Args:
        catalog: Existing ordered eligible album observation boundary.
        progress: Original candidate presenter.
        manual: Optional explicit album fallback.
    """

    catalog: AlbumSearch
    progress: Messages
    manual: ManualAlbumMatching | None = None

    async def run(
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
            self.progress.echo(
                f"Resolving album evidence {index}/{len(considered)}: "
                f"{candidate.artist} - {candidate.track}"
            )
            evidence.observe(candidate, await self._options(candidate))
        return evidence.ranked(week)

    async def _options(
        self, candidate: FoundArtCandidate
    ) -> tuple[SpotifyAlbumOption, ...]:
        options = await self.catalog.search(candidate)
        if options or self.manual is None:
            return options
        chosen = await self.manual.run(
            Scrobble(candidate.track, candidate.artist, "", 0)
        )
        if chosen is None:
            return ()
        option = manual_album_option(chosen)
        if option is None:
            self.progress.echo(
                "Selected release is not an eligible Sauvignon album or EP; skipped."
            )
            return ()
        return (option,)


async def choose_album(
    recommendation: AlbumRecommendation,
    choice_reader: AlbumChoices | None,
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
    choice = await choice_reader.choose_album(recommendation, options)
    if choice == skip_marker:
        return "skip"
    if choice == quit_marker:
        return "quit"
    for option in options:
        if option.spotify_id == choice:
            return option
    return "skip"
