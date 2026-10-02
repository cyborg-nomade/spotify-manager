"""Deterministic artist-search and one-shot interaction observations."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist


ARTIST = RankedArtist("artist", "Artist", 100, 1)
EXACT = SpotifyArtistCandidate("exact", "Artist", "uri", 50, 100, 1, True)
OTHER = SpotifyArtistCandidate("other", "Other", "uri-other", 40, 50, 2, False)


@dataclass
class MappingObservations:
    """Record original queries and exact prompted candidate lists.

    Args:
        responses: Original ordered per-query catalog observations.
        choices: Original ordered one-shot responses.
    """

    responses: list[tuple[SpotifyArtistCandidate, ...]]
    choices: list[str] = field(default_factory=list)
    searches: list[str | None] = field(default_factory=list)
    prompts: list[tuple[str, ...]] = field(default_factory=list)

    def search(
        self, artist: RankedArtist, text: str | None
    ) -> tuple[SpotifyArtistCandidate, ...]:
        """Observe the next original query without reordering its candidates.

        Args:
            artist: Original Last.fm evidence.
            text: Optional exact custom query.

        Returns:
            Original ordered candidates.
        """
        assert artist is ARTIST
        self.searches.append(text)
        return self.responses.pop(0)

    def choose(
        self, artist: RankedArtist, candidates: tuple[SpotifyArtistCandidate, ...]
    ) -> str:
        """Record the original prompt and return its next explicit response.

        Args:
            artist: Original Last.fm evidence.
            candidates: Exact original prompt list.

        Returns:
            Original choice string.
        """
        assert artist is ARTIST
        self.prompts.append(tuple(item.spotify_id for item in candidates))
        return self.choices.pop(0)
