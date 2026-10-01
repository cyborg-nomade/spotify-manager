"""Gather Palace markers in selection order with the original run-scoped cache."""

from dataclasses import dataclass
from dataclasses import field

from spotify_manager.application.palace_effects import PalaceEffects
from spotify_manager.domain.palace_albums import preferred_saved
from spotify_manager.domain.palace_values import HistoricalAlbumSelection
from spotify_manager.domain.palace_values import PalaceAlbumResult
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.models.your_library import YourLibraryAlbum


@dataclass
class PalacePlanning:
    """Resolve original alphabetical then historical markers with shared cache reuse.

    Args:
        effects: Original caller-owned catalog and presentation seams.
        saved: Original complete refreshed canonical mirror.
        threshold: Original saved-edition qualification threshold.
        cache: Original run-scoped resolved first tracks by release identity.
    """

    effects: PalaceEffects
    saved: tuple[YourLibraryAlbum, ...]
    threshold: float = 0.9
    cache: dict[str, SpotifyFirstTrack] = field(default_factory=dict)

    def alphabetical(
        self, albums: tuple[YourLibraryAlbum, ...]
    ) -> list[PalaceAlbumResult]:
        """Resolve original ordered saved selections before historical observations.

        Args:
            albums: Original selected consecutive mirror positions.

        Returns:
            Original ordered alphabetical proposals.
        """
        result = []
        for index, album in enumerate(albums, start=1):
            self.effects.progress(f"Loading alphabetical album {index}/{len(albums)}")
            mapped = SpotifyAlbum(
                album.spotify_id, album.uri, album.artist, album.album, True, 1.0
            )
            result.append(
                PalaceAlbumResult(
                    "alphabetical",
                    album.artist,
                    album.album,
                    mapped,
                    self._track(mapped),
                    "added",
                )
            )
        return result

    def historical(
        self, selections: tuple[HistoricalAlbumSelection, ...]
    ) -> list[PalaceAlbumResult]:
        """Prefer saved historical editions and reuse original resolved first markers.

        Args:
            selections: Original ordered historical selections.

        Returns:
            Original complete historical proposals, including no-match facts.
        """
        result = []
        for index, selection in enumerate(selections, start=1):
            self.effects.progress(
                f"Resolving historical album {index}/{len(selections)}"
            )
            mapped = self._historical_album(selection)
            track = self._track(mapped)
            selected = selection.album
            result.append(
                PalaceAlbumResult(
                    "history",
                    selected.artist,
                    selected.album,
                    mapped,
                    track,
                    "added" if track is not None else "no match",
                    selection.selected_date,
                    selection.date_index,
                    selection.albums_on_date,
                    selection.position,
                    selected.scrobbles,
                )
            )
        return result

    def _historical_album(
        self, selection: HistoricalAlbumSelection
    ) -> SpotifyAlbum | None:
        album = selection.album
        saved = preferred_saved(album.artist, album.album, self.saved, self.threshold)
        if saved is not None:
            return saved
        return self.effects.search(album.artist, album.album)

    def _track(self, album: SpotifyAlbum | None) -> SpotifyFirstTrack | None:
        if album is None:
            return None
        track = self.cache.get(album.spotify_id)
        if track is not None:
            return track
        track = self.effects.first_track(album)
        self.cache[album.spotify_id] = track
        return track
