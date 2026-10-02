"""Resolve artist mappings with original exact preference and custom searches."""

from collections.abc import Callable
from dataclasses import dataclass

from spotify_manager.application.release_check_values import ReleaseCheckSpotifyError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist


ArtistChoiceReader = Callable[[RankedArtist, tuple[SpotifyArtistCandidate, ...]], str]


@dataclass(frozen=True)
class _SearchRequest:
    """Carry an explicitly validated original custom query to the next observation.

    Args:
        text: Original trimmed nonempty custom query.
    """

    text: str


@dataclass(frozen=True)
class ArtistMapping:
    """Preserve initial exact mapping, original prompt lists and one-shot choices.

    Args:
        search: Original ordered catalog search boundary.
        reader: Optional original interaction callback.
        controls: Original skip, skip-artist and quit markers.
        search_prefix: Original custom-query marker.
    """

    search: Callable[[RankedArtist, str | None], tuple[SpotifyArtistCandidate, ...]]
    reader: ArtistChoiceReader | None
    controls: frozenset[str] = frozenset({"skip", "skip-artist", "quit"})
    search_prefix: str = "search:"

    def run(self, artist: RankedArtist) -> SpotifyArtistCandidate | str | None:
        """Resolve the original unique exact match or repeat explicit custom queries.

        Args:
            artist: Original ranked Last.fm evidence.

        Returns:
            Original selected mapping, control response or absent noninteractive result.

        Raises:
            ReleaseCheckSpotifyError: Mapping is ambiguous or the response is invalid.
        """
        search_text = None
        while True:
            candidates = self.search(artist, search_text)
            exact = tuple(item for item in candidates if item.exact_name)
            if search_text is None and len(exact) == 1:
                return exact[0]
            choices = candidates if search_text is not None else (exact or candidates)
            selected = self._choose(artist, choices)
            if isinstance(selected, _SearchRequest):
                search_text = selected.text
                continue
            return selected

    def _choose(
        self, artist: RankedArtist, choices: tuple[SpotifyArtistCandidate, ...]
    ) -> SpotifyArtistCandidate | str | _SearchRequest | None:
        if self.reader is None:
            _require_empty(artist, choices)
            return None
        choice = self.reader(artist, choices)
        if choice in self.controls:
            return choice
        if choice.startswith(self.search_prefix):
            text = choice.removeprefix(self.search_prefix).strip()
            if not text:
                raise ReleaseCheckSpotifyError(
                    "The custom Spotify artist search cannot be empty."
                )
            return _SearchRequest(text)
        for item in choices:
            if item.spotify_id == choice:
                return item
        raise ReleaseCheckSpotifyError("The selected Spotify artist is invalid.")


def _require_empty(
    artist: RankedArtist, choices: tuple[SpotifyArtistCandidate, ...]
) -> None:
    if not choices:
        return None
    raise ReleaseCheckSpotifyError(
        f"Spotify artist mapping is ambiguous for {artist.name}."
    )
