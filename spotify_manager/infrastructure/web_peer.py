"""Parse only the original direct socket peer for local password bypass."""

from ipaddress import ip_address


def is_loopback(host: str | None) -> bool:
    """Retain localhost and IP loopback handling without trusting forwarded headers.

    Args:
        host: Original direct socket hostname, or no peer.

    Returns:
        Original local-peer qualification.
    """
    if host is None:
        return False
    normalized = host.casefold()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False
