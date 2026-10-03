"""Read annual discovery progress and refresh canonical history before review."""

from collections.abc import Callable
from pathlib import Path

from spotify_manager.application.discovery_review import ProgressCallback
from spotify_manager.application.new_kids_values import NewKidsConfigError
from spotify_manager.application.new_kids_values import NewKidsStateError
from spotify_manager.domain import discovery_history as history_policy
from spotify_manager.domain.discovery_history import AnnualScrobbleIndex
from spotify_manager.routines import blast_from_past
from spotify_manager.routines import scrobble_history
from spotify_manager.routines.new_kids import DEFAULT_SCROBBLES_PATH


type Echo = Callable[[str], None]


def load_annual_scrobble_index(
    path: Path = DEFAULT_SCROBBLES_PATH,
    *,
    year: int,
) -> AnnualScrobbleIndex:
    """Index distinct release tracks scrobbled in one Berlin calendar year.

    Args:
        path: Existing Last.fm export path.
        year: Active local calendar year.

    Returns:
        Nonempty normalized titles grouped by artist/release identity.

    Raises:
        NewKidsStateError: Loading or decoding the source export fails.
    """
    from spotify_manager.routines.blast_from_past import load_scrobbles_by_date

    try:
        scrobbles_by_date = load_scrobbles_by_date(path)
    except blast_from_past.LastFmExportError as exc:
        raise NewKidsStateError(
            f"Could not load the {year} Last.fm scrobble history: {exc}"
        ) from exc

    return history_policy.annual_scrobble_index(scrobbles_by_date, year)


def refresh_scrobbles_for_release_progress(
    lastfm: scrobble_history.LastFmReader,
    username: str,
    *,
    scrobbles_path: Path = DEFAULT_SCROBBLES_PATH,
    echo: Echo = print,
) -> scrobble_history.ScrobbleHistorySummary:
    """Refresh shared history before deriving annual release progress.

    Args:
        lastfm: Caller-owned Last.fm history reader.
        username: Expected account name for the existing refresh workflow.
        scrobbles_path: Export path selecting canonical or explicit backup/log paths.
        echo: Existing refresh progress and completion output sink.

    Returns:
        Original history refresh summary after its completion message.

    Raises:
        ScrobbleHistoryError: Existing history refresh or persistence fails.
    """
    canonical_path = scrobbles_path.resolve() == DEFAULT_SCROBBLES_PATH.resolve()
    from spotify_manager.bootstrap.history import history_refresh

    workflow = history_refresh(
        lastfm,
        scrobbles_path,
        scrobble_history.DEFAULT_LEGACY_DELTA_PATH if canonical_path else None,
        scrobble_history.DEFAULT_BACKUP_DIR
        if canonical_path
        else scrobbles_path.parent / "lastfm_history_backups",
        scrobble_history.DEFAULT_LOG_PATH
        if canonical_path
        else scrobbles_path.parent / "scrobble_history_update_log.jsonl",
        None,
        echo,
        None,
    )
    summary = workflow.run(username, False, False)
    echo(
        "Last.fm release history ready: "
        f"{summary.live_scrobbles_added} new scrobble(s), "
        f"{summary.total_scrobbles} total."
    )
    return summary


def refresh_release_history(
    lastfm: scrobble_history.LastFmReader | None,
    username: str | None,
    label: str,
    path: Path,
    echo: Echo,
    progress: ProgressCallback | None,
) -> None:
    """Refresh discovery progress when a history source is supplied.

    Args:
        lastfm: Optional caller-owned history reader.
        username: Expected Last.fm account name.
        label: Original command label for validation errors.
        path: Original history export location.
        echo: Original progress and completion output sink.
        progress: Optional job progress callback.

    Raises:
        NewKidsConfigError: A requested refresh lacks its expected account.
        ScrobbleHistoryError: Refresh or persistence fails.
    """
    if lastfm is None:
        return
    if not username:
        raise NewKidsConfigError(
            f"LASTFM_USERNAME is required to refresh {label} release progress."
        )
    if progress:
        progress(0, 0, "Refreshing Last.fm release history")
    refresh_scrobbles_for_release_progress(
        lastfm, username, scrobbles_path=path, echo=echo
    )
