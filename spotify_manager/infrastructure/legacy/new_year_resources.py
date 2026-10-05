"""Own synchronous annual history, state and discovery observations."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

from spotipy import Spotify

from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.queue_3_import_review import AnnualImportReview
from spotify_manager.bootstrap.history import history_refresh
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure.legacy.new_year_state import LegacyAnnualState
from spotify_manager.interfaces.presenters.queue_3 import Queue3Presenter
from spotify_manager.routines import queue_3
from spotify_manager.routines import scrobble_history
from spotify_manager.settings import Settings


def _default_state() -> dict[str, object]:
    return {"years": {}}


@dataclass
class AnnualResources:
    """Retain original caller-owned annual clients and late state/destination authority.

    Args:
        sp: Original synchronous SDK client.
        lastfm: Original Last.fm reader.
        configuration: Original caller settings.
        supplied_service: Original optional shared state service.
        echo: Original visible presenter.
        cancel_check: Original optional cancellation reader.
        retry: Original annual cancellation/retry boundary.
        selected_service: Original late-resolved shared state service.
        playlists: Original late-parsed destination identities.
    """

    sp: Spotify
    lastfm: scrobble_history.LastFmReader
    configuration: Settings
    supplied_service: StateService | None
    echo: Callable[[str], None]
    cancel_check: Callable[[], bool] | None
    retry: RetryCall
    selected_service: StateService | None = None
    playlists: dict[str, str] = field(default_factory=dict)

    def destinations(self) -> dict[str, str]:
        """Parse original destinations in their original preflight order.

        Returns:
            Original exact Blast, Palace, Memory Lane and Queue 3 identities.
        """
        from spotify_manager.routines.blast_from_past import parse_playlist_id
        from spotify_manager.routines.queue_3 import (
            parse_playlist_id as default_queue_3_parse_playlist_id,
        )

        self.playlists = {
            "blast": parse_playlist_id(self.configuration.blast_from_the_past_playlist),
            "palace": parse_playlist_id(self.configuration.palace_of_memory_playlist),
            "memory": parse_playlist_id(
                self.configuration.discography_memory_lane_playlist
            ),
            "queue3": default_queue_3_parse_playlist_id(
                self.configuration.the_queue_3_playlist
            ),
        }
        return self.playlists

    def state(self) -> AnnualStateAccess:
        """Resolve original caller/runtime annual authority after destination parsing.

        Returns:
            Original shallow namespace read/write bridge.
        """
        from spotify_manager.bootstrap.state import get_state_service
        from spotify_manager.routines.new_year import validate_state

        service = self.supplied_service or get_state_service()
        self.selected_service = service
        access = service.namespace("new_year", _default_state, validate_state)
        return LegacyAnnualState(access)

    def owned(self) -> tuple[OwnedPlaylist, ...]:
        """Observe original current owned playlists excluding the auxiliary destination.

        Returns:
            Original complete current owned facts.
        """
        from spotify_manager.routines.queue_3 import load_owned_playlists

        return load_owned_playlists(self.sp, self.retry, self.playlists["queue3"])

    def history(self, preview: bool) -> tuple[Scrobble, ...]:
        """Rebuild original complete canonical history with caller account and preview.

        Args:
            preview: Original annual preview publication behavior.

        Returns:
            Original complete ordered canonical plays.
        """
        workflow = history_refresh(
            self.lastfm,
            scrobble_history.DEFAULT_SCROBBLES_PATH,
            scrobble_history.DEFAULT_LEGACY_DELTA_PATH,
            scrobble_history.DEFAULT_BACKUP_DIR,
            scrobble_history.DEFAULT_LOG_PATH,
            None,
            self.echo,
            self.cancel_check,
        )
        refreshed = workflow.run(self.configuration.lastfm_username, preview, True)
        return refreshed.history

    def discoveries(self, active_year: int, preview: bool) -> None:
        """Import original previous-year discoveries through the original public seam.

        Args:
            active_year: Original source year plus one.
            preview: Original discovery import preview behavior.
        """
        from spotify_manager.bootstrap.queue_3 import annual_inputs

        presentation = Queue3Presenter(self.echo)
        presentation.loading(active_year - 1)
        inputs = annual_inputs(
            self.sp,
            self.playlists["queue3"],
            self.retry,
            preview,
            queue_3.DEFAULT_STATE_PATH,
            self.selected_service,
            queue_3.DEFAULT_LOG_PATH,
            self.echo,
        )
        AnnualImportReview(inputs.importer, presentation).run(
            self.playlists["queue3"],
            inputs.current,
            inputs.state,
            inputs.owned,
            active_year,
            preview,
        )
