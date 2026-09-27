"""Resolve yearly Great Discoveries playlists with original creation checkpoints."""

from dataclasses import dataclass
from typing import Protocol

from spotify_manager.application.new_kids_values import NewKidsError
from spotify_manager.application.ports.state import RoutineState


class DiscoveryPlaylistCreation(Protocol):
    """Observe profile identity and create the original private yearly playlist."""

    def current_user(self) -> str:
        """Read the original current-profile identifier.

        Returns:
            Tolerantly parsed identifier, or an empty string for an invalid profile.
        """

    def create(self, user_id: str, year: int) -> str:
        """Create the original named private playlist.

        Args:
            user_id: Accepted current-profile identifier.
            year: Original review year used in the name and description.

        Returns:
            Tolerantly parsed playlist identifier, or an empty string.
        """


class DiscoveryCreationPresentation(Protocol):
    """Explain yearly destination creation at the original effect boundaries."""

    def preview_creation(self, year: int) -> None:
        """Show future creation and the original folder limitation.

        Args:
            year: Original review year.
        """

    def created(self, year: int) -> None:
        """Show successful creation after the namespace checkpoint.

        Args:
            year: Original review year.
        """


@dataclass(frozen=True)
class GreatDiscoveries:
    """Reuse, seed or create the yearly destination while preserving write order.

    Args:
        access: Profile and playlist creation effects.
        state_access: Existing namespace checkpoint boundary.
        presentation: Original creation messages.
    """

    access: DiscoveryPlaylistCreation
    state_access: RoutineState
    presentation: DiscoveryCreationPresentation

    def resolve(
        self, state: dict[str, object], year: int, seed_2026: str, dry_run: bool
    ) -> str | None:
        """Resolve the destination with the original 2026 and preview rules.

        Args:
            state: Mutable complete review namespace.
            year: Original review year.
            seed_2026: Configured existing 2026 playlist identifier.
            dry_run: Whether to suppress creation and namespace writes.

        Returns:
            Accepted identifier, or None for a preview of future creation.

        Raises:
            KeyError: The playlist container is missing.
            AssertionError: The playlist container is not a record.
            NewKidsError: Spotify returns no profile or created-playlist identifier.
        """
        playlists = state["great_discoveries_playlists"]
        assert isinstance(playlists, dict)
        stored = playlists.get(str(year))
        if isinstance(stored, str) and stored:
            return stored
        if year == 2026:
            if not dry_run:
                playlists[str(year)] = seed_2026
                self.state_access.save(state)
            return seed_2026
        if dry_run:
            self.presentation.preview_creation(year)
            return None
        playlist_id = self._create(year)
        playlists[str(year)] = playlist_id
        self.state_access.save(state)
        self.presentation.created(year)
        return playlist_id

    def _create(self, year: int) -> str:
        user_id = self.access.current_user()
        if not user_id:
            raise NewKidsError("Spotify returned an invalid current-user profile.")
        playlist_id = self.access.create(user_id, year)
        if not playlist_id:
            raise NewKidsError("Spotify did not return the created playlist id.")
        return playlist_id
