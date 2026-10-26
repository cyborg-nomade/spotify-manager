"""Success contracts for the public CLI routine wrappers."""

from dataclasses import dataclass
from datetime import UTC
from datetime import date
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from spotify_manager import main
from tests.support.feature_invocation import FeatureInvocation
from tests.support.wine_invocation import WineInvocation


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
    """Update scrobble history command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = UpdateScrobbleHistoryCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(
        main.scrobble_history, "refresh_scrobble_history", scenario.refresh
    )
    main.update_scrobble_history_command(dry_run=True)
    assert "Merged total" in capsys.readouterr().out


def test_something_old_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Something old command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = SomethingOldCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(
        main.something_old,
        "run_something_old",
        FeatureInvocation(scenario, ("playlist_id",)),
    )
    main.something_old_command(dry_run=True)
    assert "cancelled" in capsys.readouterr().out


def test_release_check_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Release check command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
        wine_cellar_duplicates_removed=0,
        history_refresh=None,
        results=(),
    )
    scenario = ReleaseCheckCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(
        main.release_check,
        "run_release_check",
        FeatureInvocation(scenario, ("playlists",)),
    )
    main.check_new_releases_command(dry_run=True)
    assert "1/1 artists complete" in capsys.readouterr().out


def test_found_art_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Found art command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = FoundArtCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(main.found_art, "run_found_art", scenario.run)
    main.found_art_command(count=20, max_playlist_length=None, dry_run=True)
    assert "Found Art" in capsys.readouterr().out


def test_fill_queue_from_lastfm_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fill queue from lastfm command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = FillQueueFromLastfmCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(
        main.the_queue,
        "fill_queue_from_lastfm",
        FeatureInvocation(scenario, ("playlists",)),
    )
    main.fill_queue_from_lastfm_command(
        count=1, max_playlist_length=None, seed_count=3, dry_run=True
    )
    assert "selected 0/1" in capsys.readouterr().out


def test_flush_queue_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Flush queue command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = FlushQueueCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(main.the_queue, "flush_queue", scenario.run)
    main.flush_queue_command(dry_run=True)
    assert "processed 10/10 artists" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["new-kids", "queue-2"])
def test_new_kids_commands_complete(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    """New kids commands complete.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
        command: Original command.
    """
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
    scenario = NewKidsCommandsCompleteScenario(summary=summary)
    monkeypatch.setattr(
        main.new_kids,
        target,
        FeatureInvocation(
            scenario,
            (
                "new_kids_playlist_id",
                "queue_2_playlist_id",
                "great_discoveries_playlist_id",
                "unlucky_ones_playlist_id",
                "newfoundland_playlist_id",
            ),
        ),
    )
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
    """Queue 3 command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = Queue3CommandCompletesScenario(summary=summary)
    monkeypatch.setattr(
        main.queue_3,
        "flush_queue_3",
        FeatureInvocation(scenario, ("playlist_id", "transition_reader")),
    )
    main.flush_queue_3_command(dry_run=True)
    assert "Queue 3" in capsys.readouterr().out


def test_new_wine_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """New wine command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = NewWineCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(main.new_wine, "flush_new_wine", WineInvocation(scenario))
    main.flush_new_wine_command(dry_run=True, no_discovery=False)
    assert "New Wine" in capsys.readouterr().out


def test_slow_listening_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Slow listening command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = SlowListeningCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(main.slow_listening, "flush_slow_listening", scenario.run)
    main.flush_slow_listening_command(dry_run=True)
    assert "Slow Listening" in capsys.readouterr().out


def test_requeue_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Requeue command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
    del configured_cli
    summary = main.requeue_for_a_dream.RequeueForADreamSummary(
        recorded_at=datetime.now(UTC),
        playlist_id=PLAYLIST_ID,
        dry_run=True,
        action="empty",
        playlist_length_before=0,
        playlist_length_after=0,
    )
    scenario = RequeueCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(
        main.requeue_for_a_dream, "flush_requeue_for_a_dream", scenario.run
    )
    main.flush_requeue_for_a_dream_command(dry_run=True)
    assert "empty" in capsys.readouterr().out.casefold()


def test_discography_command_handles_an_empty_plan(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Discography command handles an empty plan.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
    del configured_cli
    plan = main.discography.DiscographyPlan(
        start_queue="requeue",
        next_queue="memory_lane",
        artists=(),
        total_releases=0,
        open_slots=10,
    )
    scenario = DiscographyCommandHandlesAnEmptyPlanScenario(plan=plan)
    monkeypatch.setattr(main.discography, "build_discography_plan", scenario.build)
    main.plan_discographies_command(dry_run=True)
    assert "No artists" in capsys.readouterr().out


def test_palace_command_completes(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: object,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Palace command completes.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        configured_cli: Original configured cli.
        capsys: Original capsys.
    """
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
    scenario = PalaceCommandCompletesScenario(summary=summary)
    monkeypatch.setattr(
        main.palace_of_memory,
        "fill_palace_of_memory",
        FeatureInvocation(scenario, ("playlist_id",)),
    )
    main.fill_palace_of_memory_command(
        dry_run=True, alphabetical_start=None, set_alphabetical_cursor=None
    )
    assert "Palace of Memory" in capsys.readouterr().out


@dataclass
class UpdateScrobbleHistoryCommandCompletesScenario:
    """Retain the original update scrobble history command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.scrobble_history.ScrobbleHistorySummary

    def refresh(
        self, *_args: Any, **kwargs: Any
    ) -> main.scrobble_history.ScrobbleHistorySummary:
        """Execute the original refresh mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].echo("History current")
        return self.summary


@dataclass
class SomethingOldCommandCompletesScenario:
    """Retain the original something old command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.something_old.SomethingOldSummary

    def __call__(
        self, *_args: Any, **kwargs: Any
    ) -> main.something_old.SomethingOldSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].echo("Selection ready")
        return self.summary


@dataclass
class ReleaseCheckCommandCompletesScenario:
    """Retain the original release check command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.release_check.ReleaseCheckSummary

    def __call__(
        self, *_args: Any, **kwargs: Any
    ) -> main.release_check.ReleaseCheckSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].progress(1, 1, "Release check complete")
        return self.summary


@dataclass
class FoundArtCommandCompletesScenario:
    """Retain the original found art command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.found_art.FoundArtSummary

    def run(self, *_args: Any, **kwargs: Any) -> main.found_art.FoundArtSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].echo("Recommendations ready")
        return self.summary


@dataclass
class FillQueueFromLastfmCommandCompletesScenario:
    """Retain the original fill queue from lastfm command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.the_queue.FillSummary

    def __call__(self, *_args: Any, **kwargs: Any) -> main.the_queue.FillSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].progress(1, 1, "Queue recommendations complete")
        return self.summary


@dataclass
class FlushQueueCommandCompletesScenario:
    """Retain the original flush queue command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.the_queue.FlushSummary

    def run(self, *_args: Any, **kwargs: Any) -> main.the_queue.FlushSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].progress(10, 10, "Queue flush complete")
        return self.summary


@dataclass
class NewKidsCommandsCompleteScenario:
    """Retain the original new kids commands complete fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.new_kids.FlushSummary

    def __call__(self, *_args: Any, **kwargs: Any) -> main.new_kids.FlushSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["echo"].echo("Routine complete")
        kwargs["progress_callback"].progress(0, 0, "Routine complete")
        return self.summary


@dataclass
class Queue3CommandCompletesScenario:
    """Retain the original queue 3 command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.queue_3.FlushSummary

    def __call__(self, *_args: Any, **kwargs: Any) -> main.queue_3.FlushSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["echo"].echo("Queue 3 complete")
        kwargs["progress_callback"].progress(0, 0, "Queue 3 complete")
        return self.summary


@dataclass
class NewWineCommandCompletesScenario:
    """Retain the original new wine command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.new_wine.FlushSummary

    def __call__(self, *_args: Any, **kwargs: Any) -> main.new_wine.FlushSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["echo"].echo("New Wine complete")
        kwargs["progress_callback"].progress(0, 0, "New Wine complete")
        return self.summary


@dataclass
class SlowListeningCommandCompletesScenario:
    """Retain the original slow listening command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.slow_listening.FlushSummary

    def run(self, *_args: Any, **kwargs: Any) -> main.slow_listening.FlushSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["echo"].echo("Slow Listening complete")
        kwargs["progress_callback"].progress(0, 0, "Slow Listening complete")
        return self.summary


@dataclass
class RequeueCommandCompletesScenario:
    """Retain the original requeue command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.requeue_for_a_dream.RequeueForADreamSummary

    def run(
        self, *_args: Any, **kwargs: Any
    ) -> main.requeue_for_a_dream.RequeueForADreamSummary:
        """Execute the original run mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["echo"].echo("Requeue complete")
        kwargs["progress_callback"].echo("Requeue complete")
        return self.summary


@dataclass
class DiscographyCommandHandlesAnEmptyPlanScenario:
    """Retain the original discography command handles an empty plan fixture.

    Args:
        plan: Original plan observation or resource.
    """

    plan: main.discography.DiscographyPlan

    def build(self, *_args: Any, **kwargs: Any) -> main.discography.DiscographyPlan:
        """Execute the original build mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["progress_callback"].echo("Plan complete")
        return self.plan


@dataclass
class PalaceCommandCompletesScenario:
    """Retain the original palace command completes fixture.

    Args:
        summary: Original summary observation or resource.
    """

    summary: main.palace_of_memory.PalaceOfMemorySummary

    def __call__(
        self, *_args: Any, **kwargs: Any
    ) -> main.palace_of_memory.PalaceOfMemorySummary:
        """Execute the original fill mock boundary.

        Args:
            _args: Original external mock argument.
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        kwargs["echo"].echo("Palace complete")
        kwargs["progress_callback"].echo("Palace complete")
        return self.summary
