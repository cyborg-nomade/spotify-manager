"""Invoke new year use cases for CLI and HTTP features."""

from collections.abc import Callable as Callable

from spotipy import Spotify as Spotify

from spotify_manager.application.new_year_membership import RetryCall as RetryCall
from spotify_manager.bootstrap import new_year as composition
from spotify_manager.core.state.service import StateService as StateService
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines.new_year import validate_state as validate_state
from spotify_manager.settings import Settings as Settings


def run_new_year(
    sp: Spotify,
    lastfm: scrobble_history.LastFmReader,
    configuration: Settings,
    *,
    year: int | None = None,
    dry_run: bool = True,
    state_service: StateService | None = None,
    echo: Callable[[str], None] = print,
    cancel_check: Callable[[], bool] | None = None,
    retry_call: RetryCall | None = None,
) -> dict[str, object]:
    """Plan all annual markers, then preview or execute the five checkpointed stages.

    Args:
        sp: Original caller-owned SDK client.
        lastfm: Original complete history reader.
        configuration: Original caller destination/account settings.
        year: Original optional completed source year.
        dry_run: Original preview behavior, including history and discovery reads.
        state_service: Original optional shared state service.
        echo: Original visible presenter.
        cancel_check: Original optional cancellation reader.
        retry_call: Original optional caller retry boundary.

    Returns:
        Original wide result retaining stored unknown fields and key overrides.

    Raises:
        NewYearError: Original source, marker or destination authority fails.
        ScrobbleHistoryCancelledError: Original cancellation requests a stop.
    """
    return composition.compose(
        sp, lastfm, configuration, state_service, echo, cancel_check, retry_call
    ).run(year, dry_run)
