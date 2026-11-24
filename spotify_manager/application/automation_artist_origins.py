"""Refresh the nightly Artist Map backlog through the protected Space API."""

import re
from typing import Protocol
from urllib.parse import urlencode

from spotify_manager.application.automation_values import AutomationError


_HISTORY = "/lastfm/analytics/status"
_ORIGINS = "/lastfm/analytics/origins"
_NIGHTLY_LIMIT = 250
_MIN_RUNTIME = 120


class ArtistOriginsSpace(Protocol):
    """Request protected Space data within the nightly maintenance budget."""

    def request(self, method: str, path: str) -> object:
        """Return the Space response for an authenticated request."""
        ...

    def sleep(self, seconds: int) -> None:
        """Wait within the current maintenance deadline."""
        ...

    def remaining_seconds(self) -> float:
        """Return the remaining maintenance time in seconds."""
        ...


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AutomationError("Artist Map received an invalid Space response.")
    return value


def _ready_history(client: ArtistOriginsSpace) -> str:
    status = _object(client.request("GET", f"{_HISTORY}?refresh=true"))
    while status.get("checking") is True or status.get("state") == "building":
        client.sleep(5)
        status = _object(client.request("GET", _HISTORY))
    metadata = status.get("metadata")
    if status.get("state") == "ready" and isinstance(metadata, dict):
        snapshot = metadata.get("snapshot")
        if isinstance(snapshot, str) and re.fullmatch(r"v1-[0-9a-f]{64}", snapshot):
            return snapshot
    raise AutomationError("Artist Map could not pin the latest published history.")


def refresh_artist_origins(client: ArtistOriginsSpace) -> str:
    """Queue and monitor at most 250 never-looked-up artists from current history.

    Args:
        client: Authenticated Space API resource using the maintenance deadline.

    Returns:
        A safe summary of the scheduled update.

    Raises:
        AutomationError: The history, provider, or durable cache was unavailable.
    """
    if client.remaining_seconds() < _MIN_RUNTIME:
        return (
            "Too little maintenance time remains for Artist Map; retrying next night."
        )
    current = _object(client.request("GET", f"{_ORIGINS}/status"))
    if current.get("durable") is not True:
        raise AutomationError("Durable Artist Map storage is disabled on the Space.")
    if current.get("state") in ("running", "cancelling"):
        return "An Artist Map lookup is already running."
    snapshot = _ready_history(client)
    if client.remaining_seconds() < _MIN_RUNTIME:
        return (
            "Too little maintenance time remains for Artist Map; retrying next night."
        )
    parameters = urlencode({"snapshot": snapshot, "limit": _NIGHTLY_LIMIT})
    started = _object(client.request("POST", f"{_ORIGINS}/backfill?{parameters}"))
    if started.get("history_snapshot") != snapshot or _bulk_running(started):
        return "An Artist Map lookup is already running."
    return _wait_for_origins(client, started)


def _bulk_running(status: dict[str, object]) -> bool:
    total = status.get("total")
    return type(total) is int and total > _NIGHTLY_LIMIT


def _wait_for_origins(client: ArtistOriginsSpace, status: dict[str, object]) -> str:
    while status.get("state") in ("running", "cancelling"):
        client.sleep(10)
        status = _object(client.request("GET", f"{_ORIGINS}/status"))
    count = status.get("completed")
    if status.get("state") == "complete" and type(count) is int:
        return f"Artist Map saved {count} new artist lookups."
    raise AutomationError(
        "Artist Map stopped; the next run will resume saved progress."
    )
