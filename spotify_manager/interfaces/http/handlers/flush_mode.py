"""Execute named Flush Mode use cases and present admission/storage failures."""

from fastapi import HTTPException

from spotify_manager.application.flush_mode import FlushModeBlockedError
from spotify_manager.application.flush_mode import NewWineMode
from spotify_manager.application.flush_mode import check_flush_mode
from spotify_manager.application.flush_mode import new_wine_no_discovery
from spotify_manager.application.flush_mode import require_routine_start
from spotify_manager.application.ports.spotify_client import SpotifyClient
from spotify_manager.bootstrap import flush_mode as composition
from spotify_manager.core.state.models import StateError
from spotify_manager.domain.flush_mode import FlushControl
from spotify_manager.interfaces.http.models.flush_mode import FlushModeStatus
from spotify_manager.interfaces.http.presenters.flush_mode import flush_status


async def status() -> FlushModeStatus:
    """Read global mode without Spotify access or state writes.

    Returns:
        Current effective policy and retained observations.

    Raises:
        HTTPException: Shared policy cannot be read safely.
    """
    try:
        state = await composition.async_flush_mode_state().load()
    except StateError as exc:
        raise HTTPException(503, "Flush Mode state is unavailable.") from exc
    return flush_status(state)


async def control(value: FlushControl) -> FlushModeStatus:
    """Persist the operator selection without checking Spotify.

    Args:
        value: Automatic, forced on or forced off.

    Returns:
        Committed control and latest observations.

    Raises:
        HTTPException: State cannot be committed.
    """
    try:
        state = await composition.async_flush_mode_state().control(value)
    except StateError as exc:
        raise HTTPException(503, "Flush Mode control could not be saved.") from exc
    return flush_status(state)


async def check(client: SpotifyClient) -> FlushModeStatus:
    """Refresh complete counts while preserving persistent overrides.

    Args:
        client: Invocation-owned native client used only for two reads.

    Returns:
        Updated or stale state with an explicit check failure.

    Raises:
        HTTPException: Results cannot be persisted.
    """
    try:
        state = await check_flush_mode(
            composition.async_flush_mode_state(),
            composition.queue_counts(client),
            composition.FlushModeClock(),
        )
    except StateError as exc:
        raise HTTPException(503, "Flush Mode check could not be saved.") from exc
    return flush_status(state)


async def require_start(command: str) -> None:
    """Reject a new start or resume before registering a background job.

    Args:
        command: Canonical routine identity.

    Raises:
        HTTPException: Mode blocks this routine or cannot be read safely.
    """
    try:
        state = await composition.async_flush_mode_state().load()
        require_routine_start(command, state)
    except FlushModeBlockedError as exc:
        raise HTTPException(409, str(exc)) from exc
    except StateError as exc:
        raise HTTPException(
            503, "Flush Mode state is unavailable; start blocked."
        ) from exc


async def wine_mode(requested: bool) -> NewWineMode:
    """Resolve New Wine's setting once before its job is registered.

    Args:
        requested: Operator's ordinary No Discovery setting.

    Returns:
        Effective initial setting; capacity fallback remains part of the routine.

    Raises:
        HTTPException: The policy cannot be read safely.
    """
    try:
        state = await composition.async_flush_mode_state().load()
    except StateError as exc:
        raise HTTPException(
            503, "Flush Mode state is unavailable; start blocked."
        ) from exc
    return new_wine_no_discovery(requested, state)
