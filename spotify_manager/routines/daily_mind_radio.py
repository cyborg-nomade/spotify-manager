"""Build the daily mind radio playlist from anniversary scrobbles."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.routines import blast_from_past


ANNIVERSARY_INTERVAL_YEARS = 5
RandomTimestampReader = Callable[[], datetime]


@dataclass(frozen=True)
class DailyMindRadioBatch:
    """Anniversary dates and the scrobbles selected from them."""

    generated_at: datetime | None
    target_dates: tuple[date, ...]
    missing_dates: tuple[date, ...]
    selections: tuple[blast_from_past.ScrobbleSelection, ...]


@dataclass(frozen=True)
class DailyMindRadioSpotifySummary:
    """Completed Daily Mind Radio playlist update."""

    playlist_id: str
    batch: DailyMindRadioBatch
    playlist_length_before: int | None
    playlist_length_after: int | None
    results: tuple[blast_from_past.SpotifySelectionResult, ...]

    @property
    def added(self) -> int:
        """Return the number of tracks added in this run."""
        return sum(result.action == "added" for result in self.results)


def anniversary_dates(today: date, earliest_year: int) -> tuple[date, ...]:
    """Return last year's date followed by five-year steps into the past."""
    dates: list[date] = []
    for year in range(
        today.year - 1,
        earliest_year - 1,
        -ANNIVERSARY_INTERVAL_YEARS,
    ):
        try:
            dates.append(date(year, today.month, today.day))
        except ValueError:
            # February 29 has no same-day counterpart in non-leap years.
            continue
    return tuple(dates)


def select_daily_mind_radio(
    path: Path = blast_from_past.DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_timestamp_reader: RandomTimestampReader = (
        blast_from_past.fetch_random_timestamp
    ),
    progress_callback: blast_from_past.ProgressCallback | None = None,
) -> DailyMindRadioBatch:
    """Select one scrobble from each populated anniversary date."""
    if progress_callback is not None:
        progress_callback("Loading Last.fm scrobbles")
    scrobbles_by_date = blast_from_past.load_scrobbles_by_date(path)
    if not scrobbles_by_date:
        raise blast_from_past.LastFmExportError(
            "The Last.fm export does not contain any scrobbles."
        )

    current_date = today or datetime.now(blast_from_past.SCROBBLE_TIMEZONE).date()
    target_dates = anniversary_dates(
        current_date,
        earliest_year=min(scrobble_date.year for scrobble_date in scrobbles_by_date),
    )
    populated_dates = tuple(
        target_date
        for target_date in target_dates
        if scrobbles_by_date.get(target_date)
    )
    missing_dates = tuple(
        target_date
        for target_date in target_dates
        if not scrobbles_by_date.get(target_date)
    )
    if not populated_dates:
        return DailyMindRadioBatch(
            generated_at=None,
            target_dates=target_dates,
            missing_dates=missing_dates,
            selections=(),
        )

    if progress_callback is not None:
        progress_callback("Requesting a selection timestamp from Random.org")
    generated_at = random_timestamp_reader()

    if progress_callback is not None:
        progress_callback("Applying Last.fm pagination rules")
    target_indexes = {
        target_date: index for index, target_date in enumerate(target_dates)
    }
    selections = tuple(
        blast_from_past.select_scrobble(
            selected_date=selected_date,
            date_index=target_indexes[selected_date],
            scrobbles=scrobbles_by_date[selected_date],
            generated_at=generated_at,
        )
        for selected_date in populated_dates
    )
    return DailyMindRadioBatch(
        generated_at=generated_at,
        target_dates=target_dates,
        missing_dates=missing_dates,
        selections=selections,
    )


def add_daily_mind_radio_to_spotify(
    sp: Spotify,
    playlist_id: str,
    path: Path = blast_from_past.DEFAULT_SCROBBLES_PATH,
    today: date | None = None,
    random_timestamp_reader: RandomTimestampReader = (
        blast_from_past.fetch_random_timestamp
    ),
    progress_callback: blast_from_past.ProgressCallback | None = None,
) -> DailyMindRadioSpotifySummary:
    """Select anniversary scrobbles and append their Spotify matches."""
    batch = select_daily_mind_radio(
        path=path,
        today=today,
        random_timestamp_reader=random_timestamp_reader,
        progress_callback=progress_callback,
    )
    if not batch.selections:
        return DailyMindRadioSpotifySummary(
            playlist_id=playlist_id,
            batch=batch,
            playlist_length_before=None,
            playlist_length_after=None,
            results=(),
        )

    if progress_callback is not None:
        progress_callback("Loading the Spotify playlist")
    playlist = blast_from_past.load_playlist_state(sp, playlist_id)
    resolution = blast_from_past.resolve_spotify_selections(
        sp,
        batch.selections,
        playlist,
        progress_callback,
    )

    if resolution.pending_matches:
        if progress_callback is not None:
            progress_callback(
                f"Adding {len(resolution.pending_matches)} tracks to Spotify"
            )
        blast_from_past.add_spotify_matches(
            sp,
            playlist_id,
            list(resolution.pending_matches),
        )

    return DailyMindRadioSpotifySummary(
        playlist_id=playlist_id,
        batch=batch,
        playlist_length_before=playlist.total_items,
        playlist_length_after=(playlist.total_items + len(resolution.pending_matches)),
        results=resolution.results,
    )
