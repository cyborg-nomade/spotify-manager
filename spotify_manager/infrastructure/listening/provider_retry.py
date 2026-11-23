"""Interpret transient provider responses without trusting arbitrary headers."""

from datetime import UTC
from datetime import datetime
from email.utils import parsedate_to_datetime


RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3
MAX_AUTOMATIC_WAIT = 30


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
