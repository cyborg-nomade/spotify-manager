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
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import new_wine
from spotify_manager.routines import new_year as legacy
from spotify_manager.routines import palace_of_memory
from spotify_manager.routines import queue_3
from spotify_manager.routines import scrobble_history
from spotify_manager.routines import something_old
from spotify_manager.settings import Settings


def _clock() -> datetime:
    return legacy.datetime.now(legacy.BERLIN)


def _default_state() -> dict[str, object]:
    return {"years": {}}


def _playlist(
    sp: Spotify, retry: RetryCall, identity: str
) -> tuple[PlaylistTrack, ...]:
    return new_wine.load_playlist_tracks(sp, identity, retry)


def _search(
    sp: Spotify, retry: RetryCall, item: YearEntry
) -> tuple[SpotifyTrackMatch, ...]:
    play = Scrobble(artist=item["artist"], track=item["name"], album="", timestamp_ms=0)
    return blast_from_past.search_spotify_matches(sp, play, retry)


def _album(
    sp: Spotify, retry: RetryCall, artist: str, name: str
) -> SpotifyAlbum | None:
    return palace_of_memory.search_spotify_album(sp, artist, name, retry)


def _first(sp: Spotify, retry: RetryCall, album: SpotifyAlbum) -> SpotifyFirstTrack:
    return palace_of_memory.load_first_track(sp, album, retry)


def _artist(sp: Spotify, retry: RetryCall, name: str) -> SpotifyArtistCandidate | None:
    return something_old.resolve_spotify_artist(sp, name, None, retry)


def resolution(sp: Spotify, retry: RetryCall) -> AnnualResolution:
    """Bind original shared lookup seams to the named annual marker resolver.

    Args:
        sp: Original caller-owned SDK client.
        retry: Original annual cancellation/retry boundary.

    Returns:
        Complete original synchronous marker lookup owner.
    """
    return AnnualResolution(
        partial(_search, sp, retry),
        partial(_album, sp, retry),
        partial(_first, sp, retry),
        partial(_artist, sp, retry),
        partial(legacy._primary_artist, sp, retry),
    )


def membership(sp: Spotify, retry: RetryCall) -> AnnualMembership:
    """Bind original fresh membership reads and exact synchronous mutation seams.

    Args:
        sp: Original caller-owned SDK client.
        retry: Original complete retry-attempt boundary.

    Returns:
        Original fresh-membership reconciliation owner.
    """
    return AnnualMembership(
        partial(_playlist, sp, retry),
        partial(legacy._post_pending, sp),
        partial(legacy._move_position, sp),
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
        self.playlists = {
            "blast": blast_from_past.parse_playlist_id(
                self.configuration.blast_from_the_past_playlist
            ),
            "palace": blast_from_past.parse_playlist_id(
                self.configuration.palace_of_memory_playlist
            ),
            "memory": blast_from_past.parse_playlist_id(
                self.configuration.discography_memory_lane_playlist
            ),
            "queue3": queue_3.parse_playlist_id(
                self.configuration.the_queue_3_playlist
            ),
        }
        return self.playlists

    def state(self) -> AnnualStateAccess:
        """Resolve original caller/runtime annual authority after destination parsing.

        Returns:
            Original shallow namespace read/write bridge.
        """
        service = self.supplied_service or legacy.get_state_service()
        self.selected_service = service
        access = service.namespace("new_year", _default_state, legacy.validate_state)
        return LegacyAnnualState(access)

    def owned(self) -> tuple[OwnedPlaylist, ...]:
        """Observe original current owned playlists excluding the auxiliary destination.

        Returns:
            Original complete current owned facts.
        """
        return queue_3.load_owned_playlists(
            self.sp, self.retry, self.playlists["queue3"]
        )

    def history(self, preview: bool) -> tuple[Scrobble, ...]:
        """Rebuild original complete canonical history with caller account and preview.

        Args:
            preview: Original annual preview publication behavior.

        Returns:
            Original complete ordered canonical plays.
        """
        refreshed = scrobble_history.refresh_scrobble_history(
            self.lastfm,
            expected_username=self.configuration.lastfm_username,
            full_rebuild=True,
            dry_run=preview,
            progress_callback=self.echo,
            cancel_check=self.cancel_check,
        )
        return refreshed.history

    def discoveries(self, active_year: int, preview: bool) -> None:
        """Import original previous-year discoveries through the original public seam.

        Args:
            active_year: Original source year plus one.
            preview: Original discovery import preview behavior.
        """
        if preview:
            queue_3.import_previous_year_discoveries(
                self.sp,
                self.playlists["queue3"],
                active_year=active_year,
                dry_run=True,
                state_service=self.selected_service,
                retry_call=self.retry,
                echo=self.echo,
            )
            return
        queue_3.import_previous_year_discoveries(
            self.sp,
            self.playlists["queue3"],
            active_year=active_year,
            state_service=self.selected_service,
            retry_call=self.retry,
            echo=self.echo,
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
    cancel = partial(scrobble_history.check_cancel, cancel_check)
    retry = AnnualRetry(caller_retry, cancel).run
    resources = AnnualResources(
        sp, lastfm, configuration, service, echo, cancel_check, retry
    )
    effects = AnnualEffects(
        _clock,
        resources.destinations,
        resources.state,
        resources.owned,
        queue_3.find_yearly_great_discoveries,
        resources.discoveries,
        cancel,
        echo,
    )
    members = membership(sp, retry)
    charts = AnnualCharts(
        resources.owned,
        partial(legacy._create_chart, sp, retry),
        partial(_playlist, sp, retry),
        partial(legacy._replace_chart, sp, retry),
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
