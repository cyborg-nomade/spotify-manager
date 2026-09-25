"""Release completion from normalized current-year listening observations."""

from collections.abc import Set


def scrobble_threshold(tier: int, studio_minimum: int = 3) -> int:
    """Choose the distinct-track minimum for studio and fallback releases.

    Args:
        tier: Zero for preferred studio releases; other tiers are fallback releases.
        studio_minimum: Existing configured minimum for studio releases.

    Returns:
        The studio minimum for tier zero, otherwise one.
    """
    return studio_minimum if tier == 0 else 1


def release_completed(
    matched_names: Set[str],
    liked_names: Set[str],
    required_tracks: int,
) -> bool:
    """Require enough distinct played titles and every liked title among them.

    Args:
        matched_names: Normalized track titles matched to this release's history.
        liked_names: Normalized titles of its liked tracks.
        required_tracks: Distinct-title minimum for the release tier.

    Returns:
        Whether both the minimum and liked-track completeness rules hold.
    """
    return len(matched_names) >= required_tracks and liked_names <= matched_names
