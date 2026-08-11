"""Coverage for Rich summaries that form the CLI's observable contract."""

from datetime import UTC
from datetime import date
from datetime import datetime
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console

from spotify_manager import main


def _console() -> Console:
    return Console(file=StringIO(), width=180)


def _output(console: Console) -> str:
    return console.file.getvalue()  # type: ignore[union-attr]


def _history(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "export_scrobbles": 100,
        "legacy_scrobbles_added": 2,
        "live_scrobbles_added": 3,
        "total_scrobbles": 105,
        "dry_run": False,
        "persisted": False,
        "backup_path": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_scrobble_history_summary_renders_every_persistence_outcome() -> None:
    console = _console()
    main.print_scrobble_history_summary(console, _history(dry_run=True))  # type: ignore[arg-type]
    main.print_scrobble_history_summary(
        console,
        _history(persisted=True, backup_path=Path("history.backup.json")),  # type: ignore[arg-type]
    )
    main.print_scrobble_history_summary(console, _history())  # type: ignore[arg-type]

    output = _output(console)
    assert "canonical history was not changed" in output
    assert "history.backup.json" in output
    assert "already current" in output


def test_scrobble_selection_table_renders_match_and_no_match() -> None:
    selection = SimpleNamespace(
        selected_date=date(2020, 1, 1),
        page=1,
        total_pages=2,
        direction="top down",
        position=3,
        scrobble=SimpleNamespace(artist="Artist", track="Track", album=""),
    )
    results = (
        SimpleNamespace(
            selection=selection,
            match=None,
            qualifying_matches=0,
            action="no match",
        ),
        SimpleNamespace(
            selection=selection,
            match=SimpleNamespace(
                artists=("Artist",),
                track="Track",
                album="Album",
                liked=True,
                track_similarity=1.0,
                album_similarity=None,
            ),
            qualifying_matches=2,
            action="added",
        ),
    )
    console = _console()

    main.print_scrobble_selection_table(
        console,
        "Selections",
        results,  # type: ignore[arg-type]
    )

    output = _output(console)
    assert "No qualifying result" in output
    assert "liked; track 100%" in output


def test_found_art_table_renders_skip_no_match_and_match() -> None:
    candidate = SimpleNamespace(
        artist="Artist",
        track="Candidate",
        supporting_seeds=("one",),
        base_rank=1,
        weekly_rank=0.5,
        score=0.75,
        best_match=0.9,
    )
    results = (
        SimpleNamespace(
            candidate=candidate,
            match=None,
            action="artist already selected",
        ),
        SimpleNamespace(candidate=candidate, match=None, action="no Spotify match"),
        SimpleNamespace(
            candidate=candidate,
            match=SimpleNamespace(
                artists=("Artist",),
                track="Match",
                album=None,
                track_similarity=0.95,
            ),
            action="added",
        ),
    )
    console = _console()

    main.print_found_art_table(console, results)  # type: ignore[arg-type]

    output = _output(console)
    assert "Skipped after this artist was selected" in output
    assert "No unliked qualifying match" in output
    assert "Match" in output


def test_release_check_summary_renders_history_notes_and_pause_modes() -> None:
    result = SimpleNamespace(
        artist_rank=1,
        artist="Artist",
        artist_scrobbles=120,
        release="Album",
        release_type="album",
        release_date="2026-08-01",
        first_track=None,
        wine_cellar_action="would add",
        new_vintage_action="not applicable",
        reason=None,
        linked_future_release="Future Album",
    )
    base = {
        "history_refresh": _history(dry_run=True),
        "checked_from": date(2026, 1, 1),
        "checked_through": date(2026, 8, 11),
        "results": (result,),
        "resumed": True,
        "artists_processed": 1,
        "artists_total": 2,
        "wine_cellar_added": 1,
        "new_vintage_added": 0,
    }
    console = _console()
    main.print_release_check_summary(
        console,
        SimpleNamespace(**base, dry_run=True, paused=True),  # type: ignore[arg-type]
    )
    main.print_release_check_summary(
        console,
        SimpleNamespace(**base, dry_run=False, paused=True),  # type: ignore[arg-type]
    )

    output = _output(console)
    assert "part of upcoming Future Album" in output
    assert "Dry run stopped" in output
    assert "Added 1 track" in output
    assert "Rerun the command" in output


def test_something_old_summary_renders_all_terminal_actions() -> None:
    console = _console()
    main.print_something_old_summary(
        console,
        SimpleNamespace(action="playlist not empty", playlist_length_before=1),  # type: ignore[arg-type]
    )

    ranking = SimpleNamespace(
        artist="Artist",
        scrobbles=100,
        average_scrobble_ms=int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1000),
    )
    main.print_something_old_summary(
        console,
        SimpleNamespace(
            action="cancelled",
            playlist_length_before=0,
            history_refresh=_history(),
            ranking_preview=(ranking,),
        ),  # type: ignore[arg-type]
    )

    track = SimpleNamespace(
        artists=("Artist",),
        track="Track",
        album=None,
        source="lastfm",
        lastfm_scrobbles=None,
    )
    common = {
        "action": "would add",
        "playlist_length_before": 0,
        "playlist_length_after": 1,
        "history_refresh": None,
        "ranking_preview": (),
        "tracks": (track,),
    }
    main.print_something_old_summary(
        console,
        SimpleNamespace(**common, dry_run=True),  # type: ignore[arg-type]
    )
    main.print_something_old_summary(
        console,
        SimpleNamespace(**common, dry_run=False),  # type: ignore[arg-type]
    )

    output = _output(console)
    assert "already contains 1" in output
    assert "was cancelled" in output
    assert "Dry run: would add 1" in output
    assert "Something Old: 0 -> 1" in output
