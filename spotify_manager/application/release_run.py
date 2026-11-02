"""Coordinate release checking through business stages and sequential effects."""

from dataclasses import dataclass

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.application.future_release import FutureRecordMatching
from spotify_manager.application.release_artists import ReleaseArtists
from spotify_manager.application.release_check_values import ReleaseCheckSummary
from spotify_manager.application.release_destinations import load_destinations
from spotify_manager.application.release_progress import ReleaseProgress
from spotify_manager.application.release_review import ReleaseChoiceReader
from spotify_manager.application.release_review import ReleaseReview


@dataclass(frozen=True)
class ReleaseRun:
    """Run artist and release reviews with authoritative restart progress.

    Args:
        progress: Opening observations and accepted-effect boundaries.
        wine_id: Original Wine Cellar destination.
        vintage_id: Original New Vintage destination.
        reader: Optional original release-choice interaction.
        mapping: Named artist-mapping application stage.
        matching: Named containing-record matching stage.
    """

    progress: ReleaseProgress
    wine_id: str
    vintage_id: str
    reader: ReleaseChoiceReader | None
    mapping: ArtistMapping
    matching: FutureRecordMatching

    async def run(self) -> ReleaseCheckSummary:
        """Load destinations, review ordered artists and accept completion or pause.

        Returns:
            Original complete or paused workflow outcome.
        """
        destinations = await load_destinations(
            self.progress, self.wine_id, self.vintage_id
        )
        artists = ReleaseArtists(self.progress, destinations, self.mapping)
        review = ReleaseReview(self.progress, destinations, self.reader, self.matching)
        for artist in self.progress.opening.artists:
            mapped = await artists.resolve(artist)
            if mapped == "quit":
                return self._summary(destinations.duplicates, paused=True)
            if mapped is None:
                continue
            if not (await review.check_artist(artist, mapped)):
                return self._summary(destinations.duplicates, paused=True)
        await self.progress.finish()
        return self._summary(destinations.duplicates, paused=False)

    def _summary(self, duplicates: int, paused: bool) -> ReleaseCheckSummary:
        opening = self.progress.opening
        return ReleaseCheckSummary(
            opening.run_id,
            opening.checked_from,
            opening.checked_through,
            len(opening.artists),
            len(self.progress.completed),
            self.progress.preview,
            opening.resumed,
            paused,
            duplicates,
            opening.history_refresh,
            tuple(self.progress.results),
        )
