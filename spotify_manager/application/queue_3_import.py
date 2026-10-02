"""Import annual discovery artists with the original write and checkpoint order."""

from collections.abc import Callable
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from spotify_manager.application.ports.state import RoutineState
from spotify_manager.application.queue_3_values import AnnualImportResult
from spotify_manager.application.queue_3_values import Queue3ConfigError
from spotify_manager.application.queue_3_values import SeedAction
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.queue_3_import import ImportSelection
from spotify_manager.domain.queue_3_import import select_import
from spotify_manager.domain.queue_3_import import yearly_playlist_ids


def resolve_yearly_playlist(playlists: tuple[OwnedPlaylist, ...], year: int) -> str:
    """Resolve one exact yearly source while preserving configuration errors.

    Args:
        playlists: Owned playlists in observed order.
        year: Previous year to import.

    Returns:
        The sole matching playlist ID.

    Raises:
        Queue3ConfigError: No matching playlist or multiple distinct matches exist.
    """
    expected = f"Great Discoveries {year}"
    matches = yearly_playlist_ids(playlists, year)
    if not matches:
        raise Queue3ConfigError(
            f'Could not find a playlist named exactly "{expected}".'
        )
    if len(matches) > 1:
        raise Queue3ConfigError(
            f'Found multiple playlists named "{expected}"; rename the extras '
            "before running Queue 3."
        )
    return matches[0]


def _results(
    selection: ImportSelection, source_year: int, dry_run: bool
) -> tuple[AnnualImportResult, ...]:
    added_artists = {track.primary_artist_id for track in selection.additions}
    results: list[AnnualImportResult] = []
    for track in selection.considered:
        action: SeedAction = "already present"
        if track.primary_artist_id in added_artists:
            action = "would add" if dry_run else "added"
        results.append(
            AnnualImportResult(
                track.primary_artist_name, track.name, source_year, action
            )
        )
    return tuple(results)


@dataclass(frozen=True)
class AnnualDiscoveryImport:
    """Coordinate annual import effects without owning SDK or storage details.

    Args:
        read: Read parsed playlist markers using the existing retry boundary.
        append: Append all selected markers using the original batch behavior.
        audit: Record one original event and its fields.
        state_access: Persist the complete working namespace.
        present: Explain completion after writes, audits and checkpoint succeed.
        now: Read the completion timestamp only when recording a real import.
    """

    read: Callable[[str], Sequence[PlaylistTrack]]
    append: Callable[[str, list[PlaylistTrack], str], None]
    audit: Callable[[str, dict[str, object]], None]
    state_access: RoutineState
    present: Callable[[int, int, int, bool], None]
    now: Callable[[], str]

    def run(
        self,
        playlist_id: str,
        current: list[PlaylistTrack],
        state: dict[str, object],
        owned: tuple[OwnedPlaylist, ...],
        active_year: int,
        dry_run: bool,
    ) -> tuple[list[PlaylistTrack], tuple[AnnualImportResult, ...]]:
        """Import each missing primary artist once for the active year.

        Args:
            playlist_id: Destination Queue 3 identifier.
            current: Caller-owned live marker list, extended after all audits succeed.
            state: Complete mutable namespace containing annual import checkpoints.
            owned: Observed owned playlists used to resolve the previous year.
            active_year: Year used for the completion checkpoint.
            dry_run: Whether to suppress remote writes and saved completion.

        Returns:
            The same marker list and source-ordered artist decisions.

        Raises:
            Queue3ConfigError: The previous-year source cannot be resolved.
            Queue3Error: Reading the source fails at the external boundary.
            KeyError: The annual import container is absent.
            OSError: An injected effect fails; accepted earlier effects are retained.
        """
        imports = cast(dict[str, object], state["annual_imports"])
        previous = imports.get(str(active_year))
        if isinstance(previous, dict) and bool(previous.get("completed")):
            return current, ()
        source_year = active_year - 1
        source_id = resolve_yearly_playlist(owned, source_year)
        selection = select_import(current, self.read(source_id))
        results = _results(selection, source_year, dry_run)
        if selection.additions and not dry_run:
            self.append(
                playlist_id,
                list(selection.additions),
                f"importing {source_year} Great Discoveries into Queue 3",
            )
        self._audit(selection, results, active_year, source_id, dry_run)
        current.extend(selection.additions)
        if not dry_run:
            self._complete(state, imports, selection, active_year, source_id)
        self.present(source_year, len(selection.additions), len(results), dry_run)
        return current, results

    def _audit(
        self,
        selection: ImportSelection,
        results: tuple[AnnualImportResult, ...],
        active_year: int,
        source_id: str,
        dry_run: bool,
    ) -> None:
        for track, result in zip(selection.considered, results, strict=True):
            self.audit(
                "annual_import_artist",
                {
                    "active_year": active_year,
                    "source_year": active_year - 1,
                    "source_playlist_id": source_id,
                    "artist": track.primary_artist_name,
                    "artist_id": track.primary_artist_id,
                    "track": track.name,
                    "track_id": track.spotify_id,
                    "action": result.action,
                    "dry_run": dry_run,
                },
            )

    def _complete(
        self,
        state: dict[str, object],
        imports: dict[str, object],
        selection: ImportSelection,
        active_year: int,
        source_id: str,
    ) -> None:
        imports[str(active_year)] = {
            "completed": True,
            "source_year": active_year - 1,
            "source_playlist_id": source_id,
            "completed_at": self.now(),
            "artists_seen": len(selection.considered),
            "artists_added": len(selection.additions),
        }
        self.state_access.save(state)
