"""Supply independent HTTP observations for maintenance policy checks."""


def flush_payload() -> dict[str, object]:
    """Return a fresh successful policy observation without application decisions.

    Returns:
        Complete external response for a normal automatic decision.
    """
    return {
        "control": "automatic",
        "active": False,
        "automatic_active": False,
        "queue_tracks": 100,
        "queue_2_tracks": 50,
        "checked_at": "2026-09-24T00:00:00+00:00",
        "attempted_at": "2026-09-24T00:00:00+00:00",
        "error": None,
        "reason": "Automatic mode is normal; activation thresholds are not reached.",
    }
