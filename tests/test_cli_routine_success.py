"""Success contracts for the public CLI routine wrappers."""

from datetime import UTC
from datetime import date
from datetime import datetime
from types import SimpleNamespace

import pytest

from spotify_manager import main


PLAYLIST_ID = "a" * 22


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        lastfm_api_key="key",
        lastfm_username="user",
        something_old_new_playlist=PLAYLIST_ID,
        wine_cellar_playlist=PLAYLIST_ID,
        new_vintage_playlist=PLAYLIST_ID,
        found_art_playlist=PLAYLIST_ID,
        new_kids_on_the_block_playlist=PLAYLIST_ID,
        the_queue_playlist=PLAYLIST_ID,
        the_queue_2_playlist=PLAYLIST_ID,
        the_queue_3_playlist=PLAYLIST_ID,
        great_discoveries_2026_playlist=PLAYLIST_ID,
        unlucky_ones_playlist=PLAYLIST_ID,
        discography_newfoundland_playlist=PLAYLIST_ID,
        discography_memory_lane_playlist=PLAYLIST_ID,
        discography_requeue_playlist=PLAYLIST_ID,
        new_wine_from_old_bottles_playlist=PLAYLIST_ID,
        sauvignon_terre_neuve_playlist=PLAYLIST_ID,
        slow_listening_playlist=PLAYLIST_ID,
        reqeueue_for_a_dream_playlist=PLAYLIST_ID,
        palace_of_memory_playlist=PLAYLIST_ID,
    )


@pytest.fixture
def configured_cli(monkeypatch: pytest.MonkeyPatch) -> object:
    spotify = object()
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "client", lambda: spotify)
    monkeypatch.setattr(main, "review_client", lambda: spotify)
    return spotify


def test_update_scrobble_history_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.scrobble_history.ScrobbleHistorySummary(
        checked_at=datetime.now(UTC),
        username="user",
        history=(),
        export_scrobbles=10,
        legacy_scrobbles_added=0,
        live_scrobbles_added=1,
        dry_run=True,
        persisted=False,
        backup_path=None,
    )

    def refresh(*_args, **kwargs):
        kwargs["progress_callback"]("History current")
        return summary

    monkeypatch.setattr(main.scrobble_history, "refresh_scrobble_history", refresh)

    main.update_scrobble_history_command(dry_run=True)

    assert "Merged total" in capsys.readouterr().out


def test_something_old_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.something_old.SomethingOldSummary(
        generated_at=datetime.now(UTC),
        playlist_id=PLAYLIST_ID,
        playlist_length_before=0,
        playlist_length_after=0,
        dry_run=True,
        action="cancelled",
        history_refresh=None,
        ranking_preview=(),
        artist=None,
        spotify_artist=None,
        mode=None,
        release=None,
        tracks=(),
    )

    def run(*_args, **kwargs):
        kwargs["progress_callback"]("Selection ready")
        return summary

    monkeypatch.setattr(main.something_old, "run_something_old", run)

    main.something_old_command(dry_run=True)

    assert "cancelled" in capsys.readouterr().out


def test_release_check_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.release_check.ReleaseCheckSummary(
        run_id="run",
        checked_from=date(2026, 1, 1),
        checked_through=date(2026, 8, 11),
        artists_total=1,
        artists_processed=1,
        dry_run=True,
        resumed=False,
        paused=False,
        history_refresh=None,
        results=(),
    )

    def run(*_args, **kwargs):
        kwargs["progress_callback"](1, 1, "Release check complete")
        return summary

    monkeypatch.setattr(main.release_check, "run_release_check", run)

    main.check_new_releases_command(dry_run=True)

    assert "1/1 artists complete" in capsys.readouterr().out


def test_found_art_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.found_art.FoundArtSummary(
        generated_at=datetime.now(UTC),
        week_start=date(2026, 8, 10),
        playlist_id=PLAYLIST_ID,
        requested_count=20,
        seed_count=10,
        history_tracks=100,
        history_scrobbles=200,
        live_scrobbles_added=1,
        candidate_count=50,
        playlist_length_before=0,
        playlist_length_after=0,
        dry_run=True,
        seeds=(),
        results=(),
    )

    def run(*_args, **kwargs):
        kwargs["progress_callback"]("Recommendations ready")
        return summary

    monkeypatch.setattr(main.found_art, "run_found_art", run)

    main.found_art_command(count=20, max_playlist_length=None, dry_run=True)

    assert "Found Art" in capsys.readouterr().out


def test_fill_queue_from_lastfm_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.the_queue.FillSummary(
        week_start=date(2026, 8, 7),
        requested_count=1,
        history_artists=100,
        history_scrobbles=1000,
        live_scrobbles_added=1,
        seed_count=3,
        candidate_count=20,
        playlist_length_before=2,
        playlist_length_after=2,
        paused=False,
        dry_run=True,
        results=(),
    )

    def run(*_args, **kwargs):
        kwargs["progress_callback"](1, 1, "Queue recommendations complete")
        return summary

    monkeypatch.setattr(main.the_queue, "fill_queue_from_lastfm", run)

    main.fill_queue_from_lastfm_command(
        count=1,
        max_playlist_length=None,
        seed_count=3,
        dry_run=True,
    )

    assert "selected 0/1" in capsys.readouterr().out


def test_flush_queue_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.the_queue.FlushSummary(
        run_id="run",
        playlist_length_before=10,
        playlist_length_after=10,
        total=10,
        processed=10,
        resumed=False,
        dry_run=True,
        results=(),
    )

    def run(*_args, **kwargs):
        kwargs["progress_callback"](10, 10, "Queue flush complete")
        return summary

    monkeypatch.setattr(main.the_queue, "flush_queue", run)

    main.flush_queue_command(dry_run=True)

    assert "processed 10/10 artists" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["new-kids", "queue-2"])
def test_new_kids_commands_complete(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    del configured_cli
    if command == "new-kids":
        summary = main.new_kids.FlushSummary(
            results=(),
            prefill=(),
            postfill=(),
            playlist_length_before=0,
            playlist_length_after=0,
            paused=False,
            resumed=False,
            dry_run=True,
        )
        target = "flush_new_kids"
    else:
        summary = main.new_kids.Queue2Summary(
            results=(),
            prefill=(),
            queue_length_before=0,
            queue_length_after=0,
            new_kids_length_before=0,
            new_kids_length_after=0,
            paused=False,
            resumed=False,
            dry_run=True,
        )
        target = "flush_queue_2"

    def run(*_args, **kwargs):
        kwargs["echo"]("Routine complete")
        kwargs["progress_callback"](0, 0, "Routine complete")
        return summary

    monkeypatch.setattr(main.new_kids, target, run)

    if command == "new-kids":
        main.flush_new_kids_command(dry_run=True)
    else:
        main.flush_queue_2_command(dry_run=True)

    assert "complete" in capsys.readouterr().out.casefold()


def test_queue_3_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.queue_3.FlushSummary(
        run_id="run",
        total=0,
        processed=0,
        advanced=0,
        changed_releases=0,
        completed_artists=0,
        skipped=0,
        annual_import=(),
        paused=False,
        dry_run=True,
        resumed=False,
        results=(),
    )

    def run(*_args, **kwargs):
        kwargs["echo"]("Queue 3 complete")
        kwargs["progress_callback"](0, 0, "Queue 3 complete")
        return summary

    monkeypatch.setattr(main.queue_3, "flush_queue_3", run)

    main.flush_queue_3_command(dry_run=True)

    assert "Queue 3" in capsys.readouterr().out


def test_new_wine_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.new_wine.FlushSummary(
        run_id="run",
        total=0,
        processed=0,
        advanced=0,
        dropped=0,
        sent_to_sauvignon=0,
        completed_singles=0,
        skipped=0,
        albums_unsaved=0,
        paused=False,
        dry_run=True,
        resumed=False,
        results=(),
    )

    def run(*_args, **kwargs):
        kwargs["echo"]("New Wine complete")
        kwargs["progress_callback"](0, 0, "New Wine complete")
        return summary

    monkeypatch.setattr(main.new_wine, "flush_new_wine", run)

    main.flush_new_wine_command(dry_run=True, no_discovery=False)

    assert "New Wine" in capsys.readouterr().out


def test_slow_listening_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.slow_listening.FlushSummary(
        run_id="run",
        total=0,
        processed=0,
        advanced=0,
        completed_artists=0,
        skipped=0,
        paused=False,
        dry_run=True,
        resumed=False,
        results=(),
    )

    def run(*_args, **kwargs):
        kwargs["echo"]("Slow Listening complete")
        kwargs["progress_callback"](0, 0, "Slow Listening complete")
        return summary

    monkeypatch.setattr(main.slow_listening, "flush_slow_listening", run)

    main.flush_slow_listening_command(dry_run=True)

    assert "Slow Listening" in capsys.readouterr().out


def test_requeue_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    summary = main.requeue_for_a_dream.RequeueForADreamSummary(
        recorded_at=datetime.now(UTC),
        playlist_id=PLAYLIST_ID,
        dry_run=True,
        action="empty",
        playlist_length_before=0,
        playlist_length_after=0,
    )

    def run(*_args, **kwargs):
        kwargs["echo"]("Requeue complete")
        kwargs["progress_callback"]("Requeue complete")
        return summary

    monkeypatch.setattr(
        main.requeue_for_a_dream,
        "flush_requeue_for_a_dream",
        run,
    )

    main.flush_requeue_for_a_dream_command(dry_run=True)

    assert "empty" in capsys.readouterr().out.casefold()


def test_discography_command_handles_an_empty_plan(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    plan = main.discography.DiscographyPlan(
        start_queue="requeue",
        next_queue="memory_lane",
        artists=(),
        total_releases=0,
        open_slots=10,
    )

    def build(*_args, **kwargs):
        kwargs["progress_callback"]("Plan complete")
        return plan

    monkeypatch.setattr(main.discography, "build_discography_plan", build)

    main.plan_discographies_command(dry_run=True)

    assert "No artists" in capsys.readouterr().out


def test_palace_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del configured_cli
    now = datetime.now(UTC)
    summary = main.palace_of_memory.PalaceOfMemorySummary(
        generated_at=now,
        playlist_id=PLAYLIST_ID,
        dry_run=True,
        cutoff_date=date(2025, 12, 31),
        available_dates=0,
        alphabetical_start_index=0,
        alphabetical_next_index=0,
        alphabetical_cursor_overridden=False,
        playlist_length_before=0,
        playlist_length_after=0,
        album_refresh=main.palace_of_memory.SavedAlbumRefresh(
            checked_at=now,
            previous=0,
            current=0,
            added=0,
            removed=0,
            skipped=0,
            persisted=False,
            backup_path=None,
        ),
        results=(),
    )

    def fill(*_args, **kwargs):
        kwargs["echo"]("Palace complete")
        kwargs["progress_callback"]("Palace complete")
        return summary

    monkeypatch.setattr(main.palace_of_memory, "fill_palace_of_memory", fill)

    main.fill_palace_of_memory_command(
        dry_run=True,
        alphabetical_start=None,
        set_alphabetical_cursor=None,
    )

    assert "Palace of Memory" in capsys.readouterr().out
