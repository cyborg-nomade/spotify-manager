"""Shared readable labels for completed Something Old selections."""

from datetime import UTC

from spotify_manager.domain.something_old_history import PreviousMode


MODE_NAMES = {
    "lastfm_top_tracks": "Last.fm top tracks",
    "spotify_top_tracks": "Spotify top tracks",
    "album": "Album or EP",
}


def mode_history_label(previous: PreviousMode | None) -> str:
    """Describe recorded use without implying unavailable history never happened.

    Args:
        previous: Completed mode usage, or none without available evidence.

    Returns:
        Count, last recorded UTC date and optional album/provenance.
    """
    if previous is None or not previous.count or previous.last_chosen_at is None:
        return "No recorded use"
    date = previous.last_chosen_at.astimezone(UTC).date().isoformat()
    unit = "time" if previous.count == 1 else "times"
    label = f"Chosen {previous.count} {unit} · last {date}"
    if previous.release_name:
        label += f" · {previous.release_name}"
    if previous.provenance == "audit":
        label += " · imported audit"
    elif previous.provenance == "recovered":
        label += " · recovered after interruption"
    return label


def latest_choice_label(previous: tuple[PreviousMode, ...]) -> str:
    """Present the most recent recorded mode beside the explicit current options.

    Args:
        previous: Summaries for the accepted Spotify artist identity.

    Returns:
        Most recent mode label or a clear absence-of-records description.
    """
    latest = None
    latest_date = None
    for entry in previous:
        if entry.last_chosen_at is None:
            continue
        if latest_date is None or entry.last_chosen_at > latest_date:
            latest = entry
            latest_date = entry.last_chosen_at
    if latest is None:
        return "No recorded choices for this Spotify artist."
    return (
        f"Most recent recorded choice: {MODE_NAMES[latest.mode]} · "
        f"{mode_history_label(latest)}"
    )
