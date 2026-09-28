"""Compose Queue 3 business workflows with existing external boundaries."""

from collections.abc import Callable
from datetime import UTC
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.ports.listening import RetryCall
from spotify_manager.application.ports.state import RoutineState
from spotify_manager.application.queue_3_import import AnnualDiscoveryImport
from spotify_manager.infrastructure.legacy.queue_3 import LegacyAnnualImport
from spotify_manager.interfaces.presenters.queue_3 import Queue3Presenter
from spotify_manager.routines import queue_3 as legacy


def _now() -> str:
    return legacy.datetime.now(UTC).isoformat()


def annual_import(
    client: Spotify,
    retry: RetryCall,
    log_path: Path,
    state_access: RoutineState,
    echo: Callable[[str], None],
) -> AnnualDiscoveryImport:
    """Bind annual import to the caller's original request and checkpoint context.

    Args:
        client: Caller-owned Spotify client.
        retry: Existing request retry and cancellation boundary.
        log_path: Existing audit destination.
        state_access: Already resolved namespace storage.
        echo: Existing output sink.

    Returns:
        An injected annual import workflow with original effect boundaries.
    """
    access = LegacyAnnualImport(client, retry, log_path)
    presentation = Queue3Presenter(echo)
    return AnnualDiscoveryImport(
        access.read,
        access.append,
        access.audit,
        state_access,
        presentation.imported,
        _now,
    )
