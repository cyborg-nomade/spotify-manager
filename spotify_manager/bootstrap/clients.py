"""Construct caller-owned clients at the interface composition boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field

from spotify_manager.client.lastfm import LastFmClient


@dataclass(frozen=True)
class LastFmCredentials:
    """Carry validated Last.fm configuration without exposing its key in repr.

    Args:
        api_key: Caller-supplied Last.fm key.
        username: Expected account name.
    """

    api_key: str = field(repr=False)
    username: str


def lastfm_client(
    credentials: LastFmCredentials, events: Callable[[str], None] | None = None
) -> LastFmClient:
    """Construct one client with the original cache and retry defaults.

    Args:
        credentials: Validated key and account name.
        events: Invocation-owned diagnostic output.

    Returns:
        A client owned by the calling CLI invocation or HTTP worker.

    Raises:
        LastFmError: The original client rejects its configuration.
    """
    return LastFmClient(
        credentials.api_key, credentials.username, event_callback=events
    )
