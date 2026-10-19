"""Adapt Queue operator choices to the named artist-mapping application stage."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.application.artist_mapping import ArtistSearch
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.release_check_values import RankedArtist


type QueueArtistChoice = Callable[
    [ArtistRecommendation, tuple[SpotifyArtistCandidate, ...]], str
]


def _read_choice(
    reader: QueueArtistChoice,
    recommendation: ArtistRecommendation,
    _artist: RankedArtist,
    candidates: tuple[SpotifyArtistCandidate, ...],
) -> str:
    return reader(recommendation, candidates)


@dataclass(frozen=True)
class QueueArtistMapping:
    """Own the Queue prompt context while sharing the artist mapping rules.

    Args:
        catalog: Original retried candidate search integration.
        reader: Optional Queue-specific operator interaction.
    """

    catalog: ArtistSearch
    reader: QueueArtistChoice | None

    def resolve(
        self, recommendation: ArtistRecommendation
    ) -> SpotifyArtistCandidate | str | None:
        """Resolve a recommendation through the named mapping stage.

        Args:
            recommendation: Original Last.fm candidate and prompt context.

        Returns:
            Accepted artist, original control response or absent match.
        """
        artist = RankedArtist(
            recommendation.key, recommendation.artist, 0, recommendation.base_rank
        )
        reader = None
        if self.reader is not None:
            reader = partial(_read_choice, self.reader, recommendation)
        return ArtistMapping(self.catalog, reader).run(artist)
