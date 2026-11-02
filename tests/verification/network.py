"""Block outbound access in standalone verification subprocesses."""

import sys


NETWORK_EVENTS = {
    "socket.connect",
    "socket.getaddrinfo",
    "socket.gethostbyname",
    "socket.sendto",
}


def reject_network(event: str, arguments: tuple[object, ...]) -> None:
    """Reject a verification process's attempted outbound access.

    Args:
        event: Standard-library audit event.
        arguments: Original event values; deliberately never printed.

    Raises:
        AssertionError: Verification attempted network access.
    """
    if event in NETWORK_EVENTS:
        raise AssertionError("Standalone verification must remain offline.")


def install_network_guard() -> None:
    """Install the irreversible guard for this short-lived child process."""
    # Python's audit-hook API requires the handler function.
    sys.addaudithook(reject_network)
