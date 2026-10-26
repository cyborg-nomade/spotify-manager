"""Compose original synchronous annual clients, state, cancellation and presenters."""

from spotipy import Spotify

from spotify_manager.application.new_year_charts import AnnualCharts
from spotify_manager.application.new_year_discoveries import AnnualDiscoveries
from spotify_manager.application.new_year_execution import AnnualExecution
from spotify_manager.application.new_year_membership import AnnualMembership
from spotify_manager.application.new_year_membership import RetryCall
from spotify_manager.application.new_year_planning import AnnualPlanning
from spotify_manager.application.new_year_resolution import AnnualResolution
from spotify_manager.application.new_year_retry import AnnualRetry
from spotify_manager.application.new_year_run import NewYear
from spotify_manager.application.ports.runtime import CancellationState
from spotify_manager.application.ports.runtime import Messages
from spotify_manager.bootstrap.history import history_refresh
from spotify_manager.core.state.service import StateService
from spotify_manager.infrastructure.legacy.annual_catalog import LegacyAnnualCatalog
from spotify_manager.infrastructure.legacy.annual_catalog import LegacyAnnualSpotify
from spotify_manager.infrastructure.legacy.new_year_resources import (
    AnnualResources as AnnualResources,
)
from spotify_manager.interfaces.presenters.queue_3 import Queue3Presenter
from spotify_manager.routines import new_year as legacy
from spotify_manager.routines import scrobble_history
from spotify_manager.settings import Settings


def resolution(sp: Spotify, retry: RetryCall) -> AnnualResolution:
    """Construct the retained external marker-resolution entry.

    Args:
        sp: Caller-owned Spotify client.
        retry: Caller-owned retry boundary.

    Returns:
        Named annual marker resolution stage.
    """
    return AnnualResolution(LegacyAnnualSpotify(sp, retry))


def membership(sp: Spotify, retry: RetryCall) -> AnnualMembership:
    """Construct the retained external reconciliation entry.

    Args:
        sp: Caller-owned Spotify client.
        retry: Caller-owned retry boundary.

    Returns:
        Named original annual membership stage.
    """
    return AnnualMembership(LegacyAnnualSpotify(sp, retry), retry)


def compose(
    sp: Spotify,
    lastfm: scrobble_history.LastFmReader,
    configuration: Settings,
    service: StateService | None,
    echo: Messages,
    cancel_check: CancellationState | None,
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
    from spotify_manager.bootstrap.history import HistoryCancellation

    cancel = HistoryCancellation(cancel_check)
    retry = AnnualRetry(caller_retry, cancel)
    resources = AnnualResources(
        sp, lastfm, configuration, service, echo, cancel_check, retry
    )
    effects = resources
    discoveries = AnnualDiscoveries(resources, Queue3Presenter(echo))
    catalog = LegacyAnnualCatalog(sp, retry, resources)
    members = AnnualMembership(catalog, retry)
    charts = AnnualCharts(catalog, members, retry)
    planner = AnnualPlanning(
        history_refresh(
            lastfm,
            scrobble_history.DEFAULT_SCROBBLES_PATH,
            scrobble_history.DEFAULT_LEGACY_DELTA_PATH,
            scrobble_history.DEFAULT_BACKUP_DIR,
            scrobble_history.DEFAULT_LOG_PATH,
            None,
            echo,
            cancel_check,
        ),
        configuration.lastfm_username,
        catalog,
        AnnualResolution(catalog),
        echo,
        legacy.BERLIN,
    )
    return NewYear(
        effects,
        planner,
        AnnualExecution(effects, charts, members, discoveries),
        discoveries,
    )
