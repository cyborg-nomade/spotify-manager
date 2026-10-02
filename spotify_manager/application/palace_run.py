"""Coordinate Palace preflight, selection, live recheck and completion persistence."""

from dataclasses import dataclass
from datetime import date
from datetime import datetime

from spotify_manager.application.palace_effects import PalaceEffects
from spotify_manager.application.palace_effects import PalaceStateAccess
from spotify_manager.application.palace_planning import PalacePlanning
from spotify_manager.application.palace_values import PalaceOfMemorySummary
from spotify_manager.application.palace_values import SavedAlbumRefresh
from spotify_manager.domain.history_matching import PlaylistState
from spotify_manager.domain.palace_albums import alphabetical
from spotify_manager.domain.palace_albums import classify
from spotify_manager.domain.palace_values import PalaceAlbumResult
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.models.your_library import YourLibraryAlbum


@dataclass(frozen=True)
class _OpenedPalace:
    """Retain original preflight authority and selected alphabetical positions.

    Args:
        saved: Original refreshed mirror.
        refresh: Original live publication outcome.
        state: Original loaded cursor authority.
        start: Original selected zero-based starting position.
        next_index: Original zero-based next position.
        alphabetical: Original selected complete saved-album facts.
    """

    saved: tuple[YourLibraryAlbum, ...]
    refresh: SavedAlbumRefresh
    state: PalaceStateAccess
    start: int
    next_index: int
    alphabetical: tuple[YourLibraryAlbum, ...]


@dataclass(frozen=True)
class Palace:
    """Preserve original live mirror, ordered selection and cautious append authority.

    Args:
        effects: Original caller-owned observation and accepted-effect seams.
        alphabetical_count: Original configured consecutive selection size.
        match_threshold: Original saved-edition qualification threshold.
    """

    effects: PalaceEffects
    alphabetical_count: int = 5
    match_threshold: float = 0.9

    def run(
        self, playlist: str, preview: bool, override: str | None
    ) -> PalaceOfMemorySummary:
        """Resolve markers, recheck live membership and complete original persistence.

        Args:
            playlist: Original destination identity.
            preview: Original preview behavior, including mirror publication.
            override: Original optional manual alphabetical reference.

        Returns:
            Original complete selected and classified outcome.
        """
        opened = self._open(override)
        generated, cutoff, available, historical = self.effects.historical()
        self.effects.progress("Loading Palace of Memory")
        initial = self.effects.playlist(False)
        planner = PalacePlanning(self.effects, opened.saved, self.match_threshold)
        planned = planner.alphabetical(opened.alphabetical)
        planned.extend(planner.historical(historical))
        final, results, pending = self._execute(planned, initial, preview)
        return self._complete(
            opened,
            playlist,
            preview,
            override,
            generated,
            cutoff,
            available,
            final,
            results,
            pending,
        )

    def _complete(
        self,
        opened: _OpenedPalace,
        playlist: str,
        preview: bool,
        override: str | None,
        generated: datetime,
        cutoff: date,
        available: int,
        final: PlaylistState,
        results: tuple[PalaceAlbumResult, ...],
        pending: tuple[SpotifyFirstTrack, ...],
    ) -> PalaceOfMemorySummary:
        summary = _summary(
            opened,
            playlist,
            preview,
            override,
            generated,
            cutoff,
            available,
            final,
            results,
            pending,
        )
        if not preview:
            payload = self.effects.cursor_payload(
                opened.next_index, opened.alphabetical[-1]
            )
            opened.state.save(payload)
            self.effects.audit(summary)
        return summary

    def _open(self, override: str | None) -> _OpenedPalace:
        self.effects.progress("Refreshing the saved-album mirror")
        saved, refresh = self.effects.refresh()
        state = self.effects.state_access()
        cursor = state.load()
        start = self.effects.start_index(saved, override, cursor)
        selected = alphabetical(saved, start, self.alphabetical_count)
        next_index = (start + len(selected)) % len(saved)
        return _OpenedPalace(saved, refresh, state, start, next_index, selected)

    def _execute(
        self,
        planned: list[PalaceAlbumResult],
        initial: PlaylistState,
        preview: bool,
    ) -> tuple[
        PlaylistState, tuple[PalaceAlbumResult, ...], tuple[SpotifyFirstTrack, ...]
    ]:
        results, pending = classify(planned, initial.track_ids)
        if preview:
            return initial, results, pending
        self.effects.progress("Rechecking Palace of Memory")
        current = self.effects.playlist(True)
        results, pending = classify(planned, current.track_ids)
        if pending:
            self.effects.progress(f"Adding {len(pending)} first tracks to Palace")
            self.effects.append(pending)
            self.effects.echo(f"Added {len(pending)} first tracks to Palace of Memory.")
        return current, results, pending


def _summary(
    opened: _OpenedPalace,
    playlist: str,
    preview: bool,
    override: str | None,
    generated: datetime,
    cutoff: date,
    available: int,
    final: PlaylistState,
    results: tuple[PalaceAlbumResult, ...],
    pending: tuple[SpotifyFirstTrack, ...],
) -> PalaceOfMemorySummary:
    return PalaceOfMemorySummary(
        generated,
        playlist,
        preview,
        cutoff,
        available,
        opened.start,
        opened.next_index,
        override is not None,
        final.total_items,
        final.total_items + len(pending),
        opened.refresh,
        results,
    )
