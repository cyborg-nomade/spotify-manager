"""Original shared-password bypass decisions independent of HTTP or secrets I/O."""

from collections.abc import Callable


OPEN_PATHS = frozenset(
    {"/", "/index.html", "/genre-reveal", "/genre-reveal/", "/health", "/favicon.ico"}
)


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


def credential_matches(
    supplied: str,
    expected: str,
    automation: str,
    expected_automation: str | None,
    allow_loopback: bool,
    peer_is_loopback: Callable[[], bool],
    compare: Callable[[str, str], bool],
) -> bool:
    """Retain automation, lazy local-peer and constant-time password precedence.

    Args:
        supplied: Original password header.
        expected: Original configured password.
        automation: Original automation header.
        expected_automation: Original configured automation token.
        allow_loopback: Original local development flag.
        peer_is_loopback: Delayed observation of the direct socket peer.
        compare: Original constant-time comparison.

    Returns:
        Original request authorization decision.

    Raises:
        TypeError: Original string comparison rejects a supplied value.
    """
    if automation and expected_automation and compare(automation, expected_automation):
        return True
    if supplied and allow_loopback and peer_is_loopback():
        return True
    return compare(supplied, expected)
