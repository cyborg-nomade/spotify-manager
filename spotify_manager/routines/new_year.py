"""Public annual retrospective facade and original synchronous SDK boundaries."""

from collections.abc import Callable
from datetime import datetime as datetime
from functools import partial
from typing import cast
from zoneinfo import ZoneInfo

from spotipy import Spotify

from spotify_manager.application.new_year_charts import ChartKind
from spotify_manager.application.new_year_membership import RetryCall as RetryCall
from spotify_manager.application.new_year_sources import named_playlist
from spotify_manager.application.new_year_values import NewYearError as NewYearError
from spotify_manager.bootstrap import new_year as composition
from spotify_manager.core.state.runtime import get_state_service as get_state_service
from spotify_manager.core.state.service import StateService
from spotify_manager.domain.annual_history import YearEntry
from spotify_manager.domain.annual_history import rank_year as annual_ranking
from spotify_manager.domain.history import Scrobble
from spotify_manager.infrastructure import new_year_state
from spotify_manager.routines import blast_from_past as blast_from_past
from spotify_manager.routines import new_wine as new_wine
from spotify_manager.routines import palace_of_memory as palace_of_memory
from spotify_manager.routines import queue_3 as queue_3
from spotify_manager.routines import scrobble_history as scrobble_history
from spotify_manager.routines import something_old as something_old
from spotify_manager.settings import Settings


BERLIN = ZoneInfo("Europe/Berlin")


def validate_state(raw: object) -> dict[str, object]:
    """Validate original shallow annual checkpoints without normalizing stored plans.

    Args:
        raw: Original complete annual namespace.

    Returns:
        Original mutable record with every unknown field preserved.

    Raises:
        NewYearError: An original root, year or checkpoint container is invalid.
    """
    return new_year_state.validate_state(raw)


def rank_year(history: tuple[Scrobble, ...], year: int) -> dict[str, list[YearEntry]]:
    """Count original Berlin calendar-year plays with first labels and stable ties.

    Args:
        history: Original complete canonical plays.
        year: Original effective calendar year.

    Returns:
        Original complete ranked tracks, albums and artists.

    Raises:
        ValueError: The original year cannot form both calendar boundaries.
    """
    return annual_ranking(history, year, BERLIN)


def _named_playlist(
    playlists: tuple[queue_3.OwnedPlaylist, ...], name: str
) -> str | None:
    return named_playlist(playlists, name)


def _track(sp: Spotify, item: YearEntry, retry: RetryCall) -> str:
    return composition.resolution(sp, retry).track(item)


def _add_missing(
    sp: Spotify,
    playlist_id: str,
    uris: list[str],
    retry: RetryCall,
    *,
    top: bool = False,
) -> None:
    composition.membership(sp, retry).run(playlist_id, uris, top)


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
    from spotify_manager.interfaces.operations.new_year import run_new_year as operation

    return operation(
        sp,
        lastfm,
        configuration,
        year=year,
        dry_run=dry_run,
        state_service=state_service,
        echo=echo,
        cancel_check=cancel_check,
        retry_call=retry_call,
    )


def _post_pending(sp: Spotify, playlist_id: str, pending: list[str], top: bool) -> None:
    payload: dict[str, object] = {"uris": pending}
    if top:
        payload["position"] = 0
    sp._post(f"playlists/{playlist_id}/items", payload=payload)


def _move_position(sp: Spotify, playlist_id: str, position: int) -> None:
    sp._put(
        f"playlists/{playlist_id}/items",
        payload={"range_start": position, "insert_before": 0, "range_length": 1},
    )


def _replace_chart(
    sp: Spotify, retry: RetryCall, playlist_id: str, uris: list[str]
) -> None:
    retry(
        partial(sp._put, f"playlists/{playlist_id}/items", payload={"uris": uris}),
        "synchronizing the yearly chart in scrobble rank order",
    )


def _create_chart(
    sp: Spotify, retry: RetryCall, name: str, kind: ChartKind, year: int
) -> str:
    user = cast(dict[str, str], retry(sp.current_user, "loading Spotify owner"))
    created = sp.user_playlist_create(
        user["id"],
        name,
        public=False,
        description=f"Most scrobbled {kind} of {year} on Last.fm.",
    )
    return str(created["id"])


def _primary_artist(sp: Spotify, retry: RetryCall, uri: str) -> object:
    raw = cast(
        dict[str, object],
        retry(partial(sp.track, uri), "checking Memory Lane marker artist"),
    )
    artists = cast(list[dict[str, object]], raw.get("artists", [{}]))
    return artists[0].get("id")
