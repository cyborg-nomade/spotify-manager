"""Hand-counted session histories with exact gaps, ties and source disorder."""

from tests.support.listening import scrobble


def session_history() -> list[dict[str, object]]:
    """Return eight source rows forming three groups at a thirty-minute gap.

    Returns:
        Unsorted rows with a four-row tie/threshold group, a three-row group
        crossing UTC midnight, and an isolated row.
    """
    return [
        scrobble("2024-01-02T00:10:00", "Béta", "Final", ""),
        scrobble("2024-01-01T12:00:00", "Alpha", "Same"),
        scrobble("2024-01-01T12:00:00", "Alpha", "Same"),
        scrobble("2024-01-01T12:30:00", "Other", "Other"),
        scrobble("2024-01-01T12:01:00", "Béta", "Middle"),
        scrobble("2024-01-01T23:40:00", "Alpha", "First"),
        scrobble("2024-01-02T00:00:00", "Béta", "=formula"),
        scrobble("2024-01-03T12:00:00", "Solo", "Alone"),
    ]
