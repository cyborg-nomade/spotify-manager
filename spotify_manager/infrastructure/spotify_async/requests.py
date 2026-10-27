"""Preserve Requests/Spotipy URL, JSON-body and response-error contracts."""

import json
from typing import cast
from urllib.parse import urlencode

import httpx
from requests.structures import CaseInsensitiveDict
from spotipy.exceptions import SpotifyException

from spotify_manager.application.ports.spotify_async import SpotifyJson
from spotify_manager.application.ports.spotify_async import SpotifyRequest


API_ROOT = "https://api.spotify.com/v1/"


def request_url(request: SpotifyRequest) -> str:
    """Encode parameters with the synchronous adapter's null and bool behavior.

    Args:
        request: Original path and ordered query values.

    Returns:
        Complete request URL, preserving embedded market/pagination queries.
    """
    url = request.path if request.path.startswith("http") else API_ROOT + request.path
    query = {}
    for name, value in request.query.items():
        if value is not None:
            query[name] = value
    encoded = urlencode(query)
    if not encoded:
        return url
    separator = "&" if "?" in url else "?"
    return url + separator + encoded


def request_body(request: SpotifyRequest) -> bytes | None:
    """Serialize truthy payloads using the original SDK's JSON defaults.

    Args:
        request: Original JSON payload.

    Returns:
        UTF-8 body or no body, retaining falsey-payload behavior.
    """
    return json.dumps(request.payload).encode() if request.payload else None


def decode_response(response: httpx.Response) -> SpotifyJson:
    """Decode successful responses or retain the original Spotify error envelope.

    Args:
        response: Complete native HTTP response.

    Returns:
        JSON value, or none for successful empty/invalid JSON.

    Raises:
        SpotifyException: HTTP failure with original status, reason and headers.
    """
    if 400 <= response.status_code < 600:
        raise response_error(response)
    try:
        return cast(SpotifyJson, response.json())
    except ValueError:
        return None


def response_error(response: httpx.Response) -> SpotifyException:
    """Translate the synchronous SDK's HTTP error fields without reclassification.

    Args:
        response: Failed response with an attached request.

    Returns:
        Compatible Spotify exception, including Retry-After and reason.
    """
    try:
        payload = cast(dict[str, dict[str, SpotifyJson]], response.json())
        error = payload.get("error", {})
        message = error.get("message")
        reason = error.get("reason")
    except ValueError:
        message = response.text or None
        reason = None
    return SpotifyException(
        response.status_code,
        -1,
        f"{response.url}:\n {message}",
        reason=reason,
        headers=CaseInsensitiveDict(response.headers),
    )
