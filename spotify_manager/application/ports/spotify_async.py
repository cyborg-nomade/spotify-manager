"""Asynchronous Spotify boundary values without SDK or HTTP-library imports."""

from dataclasses import dataclass
from dataclasses import field
from typing import Literal
from typing import Protocol


type SpotifyJson = (
    None | bool | int | float | str | list[SpotifyJson] | dict[str, SpotifyJson]
)
type QueryValue = str | int | bool | None
type HttpMethod = Literal["GET", "POST", "PUT", "DELETE"]


@dataclass(frozen=True)
class SpotifyRequest:
    """Describe one Spotify observation or ordered mutation.

    Args:
        method: Original HTTP operation.
        path: Relative API path or complete pagination URL.
        query: Ordered parameters, omitting null values on the wire.
        payload: Original JSON body, including its original empty-body semantics.
    """

    method: HttpMethod
    path: str
    query: dict[str, QueryValue] = field(default_factory=dict)
    payload: SpotifyJson = None


class SpotifyTransport(Protocol):
    """Execute one request with the selected credential and retry profile."""

    async def request(self, request: SpotifyRequest) -> SpotifyJson:
        """Await a native request without hiding a supplied operation.

        Args:
            request: Complete request values.

        Returns:
            Original decoded JSON value, or none for an empty/invalid JSON body.
        """
        ...


class AsyncWait(Protocol):
    """Own interruptible asynchronous retry delays."""

    async def sleep(self, seconds: float) -> None:
        """Wait without blocking unrelated requests.

        Args:
            seconds: Original retry delay.
        """
        ...
