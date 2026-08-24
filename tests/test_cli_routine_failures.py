"""Shared failure-contract tests for interactive playlist CLI routines."""

from collections.abc import Callable
from types import ModuleType
from types import SimpleNamespace

import pytest
from spotipy.exceptions import SpotifyException

from spotify_manager import main


Command = Callable[[], None]


def _settings() -> SimpleNamespace:
    """Return valid playlist references for every command in this module."""
    return SimpleNamespace(
        new_kids_on_the_block_playlist="newkids",
        the_queue_2_playlist="queue2",
        the_queue_3_playlist="queue3",
        great_discoveries_2026_playlist="great",
        unlucky_ones_playlist="unlucky",
        discography_newfoundland_playlist="newfoundland",
        discography_memory_lane_playlist="memorylane",
        discography_requeue_playlist="requeue",
        slow_listening_playlist="slow",
        reqeueue_for_a_dream_playlist="dream",
        palace_of_memory_playlist="palace",
        lastfm_api_key="lastfm-key",
        lastfm_username="lastfm-user",
    )


ROUTINES: tuple[
    tuple[str, Command, ModuleType, str, Exception],
    ...,
] = (
    (
        "new-kids",
        lambda: main.flush_new_kids_command(dry_run=True),
        main.new_kids,
        "flush_new_kids",
        main.new_kids.NewKidsError("new kids failed"),
    ),
    (
        "queue-2",
        lambda: main.flush_queue_2_command(dry_run=True),
        main.new_kids,
        "flush_queue_2",
        main.new_kids.NewKidsError("queue 2 failed"),
    ),
    (
        "queue-3",
        lambda: main.flush_queue_3_command(dry_run=True),
        main.queue_3,
        "flush_queue_3",
        main.queue_3.Queue3Error("queue 3 failed"),
    ),
    (
        "slow-listening",
        lambda: main.flush_slow_listening_command(dry_run=True),
        main.slow_listening,
        "flush_slow_listening",
        main.slow_listening.SlowListeningError("slow listening failed"),
    ),
    (
        "requeue",
        lambda: main.flush_requeue_for_a_dream_command(dry_run=True),
        main.requeue_for_a_dream,
        "flush_requeue_for_a_dream",
        main.requeue_for_a_dream.RequeueForADreamError("requeue failed"),
    ),
    (
        "discography",
        lambda: main.plan_discographies_command(dry_run=True),
        main.discography,
        "build_discography_plan",
        main.discography.DiscographyError("discography failed"),
    ),
    (
        "palace",
        lambda: main.fill_palace_of_memory_command(
            dry_run=True,
            alphabetical_start=None,
            set_alphabetical_cursor=None,
        ),
        main.palace_of_memory,
        "fill_palace_of_memory",
        main.palace_of_memory.PalaceOfMemoryError("palace failed"),
    ),
)


@pytest.mark.parametrize(
    ("_name", "command", "module", "target", "domain_error"),
    ROUTINES,
    ids=[item[0] for item in ROUTINES],
)
@pytest.mark.parametrize("failure_kind", ["rate", "transient", "domain", "spotify"])
def test_interactive_routines_report_operational_failures(
    monkeypatch: pytest.MonkeyPatch,
    _name: str,
    command: Command,
    module: ModuleType,
    target: str,
    domain_error: Exception,
    failure_kind: str,
) -> None:
    errors: dict[str, BaseException] = {
        "rate": main.review_album_limits.SpotifyRateLimitError(120),
        "transient": main.review_album_limits.SpotifyTransientServerError(
            502,
            "loading playlist",
            3,
        ),
        "domain": domain_error,
        "spotify": SpotifyException(500, -1, "server failed"),
    }
    error = errors[failure_kind]
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "review_client", lambda: object())

    def fail(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(module, target, fail)

    with pytest.raises(main.typer.Exit) as exc:
        command()

    expected_code = 0 if failure_kind in {"rate", "transient"} else 1
    assert exc.value.exit_code == expected_code


@pytest.mark.parametrize(
    ("_name", "command", "module", "target", "_domain_error"),
    ROUTINES[:4] + (ROUTINES[5],),
    ids=[item[0] for item in ROUTINES[:4] + (ROUTINES[5],)],
)
def test_interruptible_routines_pause_cleanly(
    monkeypatch: pytest.MonkeyPatch,
    _name: str,
    command: Command,
    module: ModuleType,
    target: str,
    _domain_error: Exception,
) -> None:
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "review_client", lambda: object())

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(module, target, interrupt)

    with pytest.raises(main.typer.Exit) as exc:
        command()

    assert exc.value.exit_code == 0


@pytest.mark.parametrize(
    ("_name", "command", "_module", "_target", "_domain_error"),
    ROUTINES,
    ids=[item[0] for item in ROUTINES],
)
def test_interactive_routines_report_missing_playlist_configuration(
    monkeypatch: pytest.MonkeyPatch,
    _name: str,
    command: Command,
    _module: ModuleType,
    _target: str,
    _domain_error: Exception,
) -> None:
    missing = _settings()
    for attribute in vars(missing):
        setattr(missing, attribute, None)
    monkeypatch.setattr(main, "Settings", lambda: missing)

    with pytest.raises(main.typer.Exit) as exc:
        command()

    assert exc.value.exit_code == 1
