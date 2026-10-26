"""Adapt Queue operator choices to the named artist-mapping application stage."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.artist_mapping import ArtistMapping
from spotify_manager.application.artist_mapping import ArtistSearch
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.queue_values import ArtistRecommendation
from spotify_manager.domain.release_check_values import RankedArtist


class QueueArtistChoice(Protocol):
    """Own the operator interaction for choose artist."""

    def choose_artist(
        self,
        artist: ArtistRecommendation,
        candidates: tuple[SpotifyArtistCandidate, ...],
        /,
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


@dataclass(frozen=True)
class QueueMappingChoice:
    """Retain the original Queue recommendation in an artist-search prompt.

    Args:
        reader: Queue operator owning the prompt.
        recommendation: Original ranked recommendation.
    """

    reader: QueueArtistChoice
    recommendation: ArtistRecommendation

    def choose_artist(
        self, artist: RankedArtist, candidates: tuple[SpotifyArtistCandidate, ...], /
    ) -> str:
        """Read the Queue-specific prompt after the shared search.

        Args:
            artist: Search identity; the Queue recommendation retains its evidence.
            candidates: Ordered mapped candidates.

        Returns:
            Original Queue operator response.
        """
        return self.reader.choose_artist(self.recommendation, candidates)


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
            reader = QueueMappingChoice(self.reader, recommendation)
        return ArtistMapping(self.catalog, reader).run(artist)
