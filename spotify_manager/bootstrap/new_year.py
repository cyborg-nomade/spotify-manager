"""Compose original synchronous annual clients, state, cancellation and presenters."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from functools import partial

from spotipy import Spotify

from spotify_manager.application.new_year_charts import AnnualCharts
from spotify_manager.application.new_year_effects import AnnualEffects
from spotify_manager.application.new_year_effects import AnnualStateAccess
from spotify_manager.application.new_year_execution import AnnualExecution
from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.new_year_planning import AnnualPlanning
from spotify_manager.application.new_year_resolution import AnnualResolution
from spotify_manager.application.new_year_retry import AnnualRetry
from spotify_manager.application.new_year_run import NewYear
from spotify_manager.application.queue_3_import_review import AnnualImportReview
from spotify_manager.bootstrap.history import history_refresh
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.catalog import PlaylistTrack
from spotify_manager.domain.composers import OwnedPlaylist
from spotify_manager.domain.golden_selection import SpotifyArtistCandidate
from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.domain.palace_values import SpotifyAlbum
from spotify_manager.domain.palace_values import SpotifyFirstTrack
from spotify_manager.infrastructure.legacy.new_year_state import LegacyAnnualState
from spotify_manager.interfaces.presenters.queue_3 import Queue3Presenter
from spotify_manager.routines import new_year as legacy
from spotify_manager.routines import queue_3
from spotify_manager.routines import scrobble_history
from spotify_manager.settings import Settings


def _clock() -> datetime:
    return legacy.datetime.now(legacy.BERLIN)


def _default_state() -> dict[str, object]:
    return {"years": {}}


def _playlist(
    sp: Spotify, retry: RetryCall, identity: str
) -> tuple[PlaylistTrack, ...]:
    from spotify_manager.routines.new_wine import load_playlist_tracks

    return load_playlist_tracks(sp, identity, retry)


def _search(
    sp: Spotify, retry: RetryCall, item: YearEntry
) -> tuple[SpotifyTrackMatch, ...]:
    from spotify_manager.routines.blast_from_past import search_spotify_matches

    play = Scrobble(artist=item["artist"], track=item["name"], album="", timestamp_ms=0)
    return search_spotify_matches(sp, play, retry)


def _album(
    sp: Spotify, retry: RetryCall, artist: str, name: str
) -> SpotifyAlbum | None:
    from spotify_manager.routines.palace_of_memory import search_spotify_album

    return search_spotify_album(sp, artist, name, retry)


def _first(sp: Spotify, retry: RetryCall, album: SpotifyAlbum) -> SpotifyFirstTrack:
    from spotify_manager.routines.palace_of_memory import load_first_track

    return load_first_track(sp, album, retry)


def _artist(sp: Spotify, retry: RetryCall, name: str) -> SpotifyArtistCandidate | None:
    from spotify_manager.routines.something_old import resolve_spotify_artist

    return resolve_spotify_artist(sp, name, None, retry)


def resolution(sp: Spotify, retry: RetryCall) -> AnnualResolution:
    """Bind original shared lookup seams to the named annual marker resolver.

    Args:
        sp: Original caller-owned SDK client.
        retry: Original annual cancellation/retry boundary.

    Returns:
        Complete original synchronous marker lookup owner.
    """
    from spotify_manager.routines.new_year import _primary_artist

    return AnnualResolution(
        partial(_search, sp, retry),
        partial(_album, sp, retry),
        partial(_first, sp, retry),
        partial(_artist, sp, retry),
        partial(_primary_artist, sp, retry),
    )


def membership(sp: Spotify, retry: RetryCall) -> AnnualMembership:
    """Bind original fresh membership reads and exact synchronous mutation seams.

    Args:
        sp: Original caller-owned SDK client.
        retry: Original complete retry-attempt boundary.

    Returns:
        Original fresh-membership reconciliation owner.
    """
    from spotify_manager.routines.new_year import _move_position
    from spotify_manager.routines.new_year import _post_pending

    return AnnualMembership(
        partial(_playlist, sp, retry),
        partial(_post_pending, sp),
        partial(_move_position, sp),
        retry,
    )


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


def compose(
    sp: Spotify,
    lastfm: scrobble_history.LastFmReader,
    configuration: Settings,
    service: StateService | None,
    echo: Callable[[str], None],
    cancel_check: Callable[[], bool] | None,
    caller_retry: RetryCall | None,
) -> NewYear:
    """Bind original caller resources without performing preflight or external effects.

    Args:
        sp: Original caller-owned synchronous SDK client.
        lastfm: Original Last.fm reader.
        configuration: Original complete caller settings.
        service: Original optional shared service.
        echo: Original visible presenter.
        cancel_check: Original optional cancellation reader.
        caller_retry: Original optional caller retry.

    Returns:
        Original complete synchronous annual retrospective use case.
    """
    from spotify_manager.routines.new_year import _create_chart
    from spotify_manager.routines.new_year import _replace_chart
    from spotify_manager.routines.queue_3 import find_yearly_great_discoveries
    from spotify_manager.routines.scrobble_history import check_cancel

    cancel = partial(check_cancel, cancel_check)
    retry = AnnualRetry(caller_retry, cancel).run
    resources = AnnualResources(
        sp, lastfm, configuration, service, echo, cancel_check, retry
    )
    effects = AnnualEffects(
        _clock,
        resources.destinations,
        resources.state,
        resources.owned,
        find_yearly_great_discoveries,
        resources.discoveries,
        cancel,
        echo,
    )
    members = membership(sp, retry)
    charts = AnnualCharts(
        resources.owned,
        partial(_create_chart, sp, retry),
        partial(_playlist, sp, retry),
        partial(_replace_chart, sp, retry),
        members,
        retry,
    )
    planner = AnnualPlanning(
        resources.history,
        partial(_playlist, sp, retry),
        resolution(sp, retry),
        echo,
        legacy.BERLIN,
    )
    return NewYear(effects, planner, AnnualExecution(effects, charts, members))
