"""Original shared-password bypass decisions independent of HTTP or secrets I/O."""

import hmac
from typing import Protocol


LISTENING_ASSETS = frozenset(
    {
        "explorer-v1.js",
        "charts-v1.js",
        "eras-v1.js",
        "tables-v1.js",
        "explorer-v1.css",
        "echarts-6.0.0.min.js",
        "ECHARTS-LICENSE.txt",
        "ECHARTS-NOTICE.txt",
    }
)
OPEN_PATHS = frozenset(
    {
        "/",
        "/index.html",
        "/genre-reveal",
        "/genre-reveal/",
        "/health",
        "/favicon.ico",
        "/lastfm",
        "/lastfm/",
    }
    | {"/lastfm/assets/" + name for name in LISTENING_ASSETS}
)


def listening_asset_cache_control(filename: str) -> str:
    """Keep mutable explorer code fresh while retaining the pinned chart cache.

    Args:
        filename: Explicitly allowed explorer asset basename.

    Returns:
        Revalidation policy for application assets or immutable chart bytes.
    """
    if filename == "echarts-6.0.0.min.js":
        return "public, max-age=31536000, immutable"
    return "no-cache"


def is_open(password: str | None, method: str, path: str) -> bool:
    """Select original ungated requests before observing credentials.

    Args:
        password: Original configured password or disabled gate.
        method: Original HTTP method.
        path: Original URL path without query parameters.

    Returns:
        Whether the original gate allows the request without credential reads.
    """
    return password is None or method == "OPTIONS" or path in OPEN_PATHS


class RequestPeer(Protocol):
    """Observe the direct socket peer only when local bypass is considered."""

    def is_loopback(self) -> bool:
        """Read whether the direct peer is local.

        Returns:
            Whether the socket peer is a loopback address.
        """
        ...


def credential_matches(
    supplied: str,
    expected: str,
    automation: str,
    expected_automation: str | None,
    allow_loopback: bool,
    peer: RequestPeer,
) -> bool:
    """Retain automation, lazy local-peer and constant-time password precedence.

    Args:
        supplied: Original password header.
        expected: Original configured password.
        automation: Original automation header.
        expected_automation: Original configured automation token.
        allow_loopback: Original local development flag.
        peer: Delayed observation of the direct socket peer.

    Returns:
        Original request authorization decision.

    Raises:
        TypeError: Original string comparison rejects a supplied value.
    """
    if (
        automation
        and expected_automation
        and hmac.compare_digest(automation, expected_automation)
    ):
        return True
    if supplied and allow_loopback and peer.is_loopback():
        return True
    return hmac.compare_digest(supplied, expected)
