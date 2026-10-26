"""Own synchronous annual history, state and discovery observations."""

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime

from spotipy import Spotify

from spotify_manager.application.new_year_discoveries import AnnualDiscoveryInputs
from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.infrastructure.legacy.new_year_state import LegacyAnnualState
from spotify_manager.infrastructure.routine_state_codecs import NewYearStateDefinition
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
        output: Invocation-owned message output.
    """

    sp: Spotify
    lastfm: scrobble_history.LastFmReader
    configuration: Settings
    supplied_service: StateService | None
    output: Messages
    cancel_check: CancellationState | None
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

    def echo(self, message: str) -> None:
        """Present an annual observation through the invocation's output.

        Args:
            message: Original complete observation.
        """
        self.output.echo(message)

    def state(self) -> AnnualStateAccess:
        """Resolve original caller/runtime annual authority after destination parsing.

        Returns:
            Original shallow namespace read/write bridge.
        """
        from spotify_manager.bootstrap.state import get_state_service

        service = self.supplied_service or get_state_service()
        self.selected_service = service
        access = service.namespace("new_year", NewYearStateDefinition())
        return LegacyAnnualState(access)

    def owned(self) -> tuple[OwnedPlaylist, ...]:
        """Observe original current owned playlists excluding the auxiliary destination.

        Returns:
            Original complete current owned facts.
        """
        from spotify_manager.routines.queue_3 import load_owned_playlists

        return load_owned_playlists(self.sp, self.retry, self.playlists["queue3"])

    def clock(self) -> datetime:
        """Read the original effective calendar time before other boundaries.

        Returns:
            Current timestamp in the configured Berlin timezone.
        """
        from spotify_manager.routines import new_year

        return new_year.datetime.now(new_year.BERLIN)

    def cancel(self) -> None:
        """Check original operator cancellation at an accepted annual boundary."""
        from spotify_manager.routines.scrobble_history import check_cancel

        check_cancel(self.cancel_check)

    def discovery_inputs(self, preview: bool) -> AnnualDiscoveryInputs:
        """Observe annual import inputs without running another application stage.

        Args:
            preview: Whether original namespace authority is preview-cloned.

        Returns:
            Original complete import observations and configured import stage.
        """
        from spotify_manager.bootstrap.queue_3 import annual_inputs

        playlist = self.playlists["queue3"]
        inputs = annual_inputs(
            self.sp,
            playlist,
            self.retry,
            preview,
            queue_3.DEFAULT_STATE_PATH,
            self.selected_service,
            queue_3.DEFAULT_LOG_PATH,
            self,
        )
        return AnnualDiscoveryInputs(
            playlist, inputs.current, inputs.state, inputs.owned, inputs.importer
        )
