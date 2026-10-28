"""Resolve artist mappings with original exact preference and custom searches."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.release_check_values import ReleaseCheckSpotifyError
from spotify_manager.domain.artist_mapping import SpotifyArtistCandidate
from spotify_manager.domain.release_check_values import RankedArtist


class ArtistChoiceReader(Protocol):
    """Own the operator interaction for choose artist."""

    async def choose_artist(
        self, artist: RankedArtist, candidates: tuple[SpotifyArtistCandidate, ...], /
    ) -> str:
        """Read or report the original operator interaction.

        Args:
            artist: Original interaction value.
            candidates: Original interaction value.

        Returns:
            Original interaction result.
        """
        ...


class ArtistSearch(Protocol):
    """Read exact or custom-query artist candidates."""

    async def search(
        self, artist: RankedArtist, text: str | None
    ) -> tuple[SpotifyArtistCandidate, ...]:
        """Read candidates in original search order.

        Args:
            artist: Original ranked Last.fm evidence.
            text: Optional explicit custom query.

        Returns:
            Original ordered candidates and exact-name facts.
        """


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
        catalog: Original ordered catalog search integration.
        reader: Optional original interaction callback.
        controls: Original skip, skip-artist and quit markers.
        search_prefix: Original custom-query marker.
    """

    catalog: ArtistSearch
    reader: ArtistChoiceReader | None
    controls: frozenset[str] = frozenset({"skip", "skip-artist", "quit"})
    search_prefix: str = "search:"

    async def run(self, artist: RankedArtist) -> SpotifyArtistCandidate | str | None:
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
            candidates = await self.catalog.search(artist, search_text)
            exact = tuple(item for item in candidates if item.exact_name)
            if search_text is None and len(exact) == 1:
                return exact[0]
            choices = candidates if search_text is not None else (exact or candidates)
            selected = await self._choose(artist, choices)
            if isinstance(selected, _SearchRequest):
                search_text = selected.text
                continue
            return selected

    async def _choose(
        self, artist: RankedArtist, choices: tuple[SpotifyArtistCandidate, ...]
    ) -> SpotifyArtistCandidate | str | _SearchRequest | None:
        if self.reader is None:
            _require_empty(artist, choices)
            return None
        choice = await self.reader.choose_artist(artist, choices)
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
