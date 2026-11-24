"""Interpret transient provider responses without trusting arbitrary headers."""

from datetime import UTC
from datetime import datetime
from email.utils import parsedate_to_datetime


RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
RETRY_DELAYS = (5, 10, 20, 40, 60)
MAX_AUTOMATIC_WAIT = 120
MAX_RETRY_WAIT_TOTAL = 240


def retry_stop_message(retry_after: float) -> str:
    """Explain why a temporary failure stopped the current lookup.

    Args:
        retry_after: Minimum delay requested by the last provider response.

    Returns:
        A safe explanation suitable for the existing progress panel.
    """
    if retry_after > MAX_AUTOMATIC_WAIT:
        return "The provider asked for a longer pause. Try Fetch again later."
    return "The provider stayed unavailable within the automatic retry limits."


def retry_after_seconds(header: str | None) -> float:
    """Parse HTTP delay seconds or a dated Retry-After value.

    Args:
        header: Optional untrusted public response header.

    Returns:
        Nonnegative delay in seconds. Invalid values grant no extra delay.
    """
    value = (header or "").strip()
    if not value or len(value) > 80:
        return 0
    if value.isascii() and value.isdigit():
        return float(value)
    try:
        until = parsedate_to_datetime(value)
        if until.tzinfo is None:
            until = until.replace(tzinfo=UTC)
        return max(0.0, (until - datetime.now(UTC)).total_seconds())
    except ValueError, OverflowError:
        return 0
