"""Operational error rendering for Last.fm-backed CLI routines."""

from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy.exceptions import SpotifyException

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
    )


@pytest.fixture
def configured_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "Settings", _settings)
    monkeypatch.setattr(main, "client", lambda: object())


@pytest.mark.parametrize("failure_stage", ["configuration", "refresh"])
def test_scrobble_history_command_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configured_cli: None,
    failure_stage: str,
) -> None:
    del configured_cli
    if failure_stage == "configuration":
        monkeypatch.setattr(
            main.found_art,
            "validate_lastfm_configuration",
            lambda *_args: (_ for _ in ()).throw(
                main.found_art.FoundArtConfigError("missing Last.fm key")
            ),
        )
    else:
        monkeypatch.setattr(
            main.scrobble_history,
            "refresh_scrobble_history",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                main.scrobble_history.ScrobbleHistoryError("history failed")
            ),
        )

    with pytest.raises(main.typer.Exit) as exc:
        main.update_scrobble_history_command(dry_run=True)

    assert exc.value.exit_code == 1
    output = capsys.readouterr().out.casefold()
    assert "failed" in output or failure_stage == "configuration"


@pytest.mark.parametrize(
    "error",
    [
        main.something_old.SomethingOldError("selection failed"),
        SpotifyException(500, -1, "server failed"),
    ],
)
def test_something_old_command_reports_operational_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configured_cli: None,
    error: Exception,
) -> None:
    del configured_cli
    monkeypatch.setattr(
        main.something_old,
        "run_something_old",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.something_old_command(dry_run=True)

    assert exc.value.exit_code == 1
    assert capsys.readouterr().out


def test_something_old_command_reports_bad_configuration(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: None,
) -> None:
    del configured_cli
    monkeypatch.setattr(
        main.something_old,
        "parse_playlist_id",
        lambda _value: (_ for _ in ()).throw(
            main.something_old.SomethingOldConfigError("missing playlist")
        ),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.something_old_command(dry_run=True)

    assert exc.value.exit_code == 1


@pytest.mark.parametrize(
    ("error", "dry_run", "exit_code"),
    [
        (KeyboardInterrupt(), True, 0),
        (KeyboardInterrupt(), False, 0),
        (main.release_check.ReleaseCheckError("check failed"), False, 1),
        (SpotifyException(500, -1, "server failed"), False, 1),
        (RequestsConnectionError("connection reset"), False, 1),
    ],
)
def test_release_check_command_reports_each_stop_condition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    configured_cli: None,
    error: BaseException,
    dry_run: bool,
    exit_code: int,
) -> None:
    del configured_cli
    monkeypatch.setattr(
        main.release_check,
        "run_release_check",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.check_new_releases_command(dry_run=dry_run)

    assert exc.value.exit_code == exit_code
    assert capsys.readouterr().out


def test_release_check_command_reports_bad_configuration(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: None,
) -> None:
    del configured_cli
    monkeypatch.setattr(
        main.release_check.ReleaseCheckPlaylists,
        "from_references",
        lambda *_args: (_ for _ in ()).throw(
            main.release_check.ReleaseCheckConfigError("missing playlists")
        ),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.check_new_releases_command(dry_run=True)

    assert exc.value.exit_code == 1


def test_found_art_command_validates_exclusive_size_options() -> None:
    with pytest.raises(main.typer.BadParameter):
        main.found_art_command(
            count=1,
            max_playlist_length=2,
            seed_count=1,
            dry_run=True,
        )


@pytest.mark.parametrize(
    "error",
    [
        main.found_art.FoundArtError("recommendation failed"),
        SpotifyException(500, -1, "server failed"),
    ],
)
def test_found_art_command_reports_operational_failures(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: None,
    error: Exception,
) -> None:
    del configured_cli
    monkeypatch.setattr(
        main.found_art,
        "run_found_art",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.found_art_command(
            count=None,
            max_playlist_length=None,
            seed_count=10,
            dry_run=True,
        )

    assert exc.value.exit_code == 1


def test_found_art_command_reports_bad_configuration(
    monkeypatch: pytest.MonkeyPatch,
    configured_cli: None,
) -> None:
    del configured_cli
    monkeypatch.setattr(
        main.found_art,
        "parse_found_art_playlist_id",
        lambda _value: (_ for _ in ()).throw(
            main.found_art.FoundArtConfigError("missing playlist")
        ),
    )

    with pytest.raises(main.typer.Exit) as exc:
        main.found_art_command(
            count=None,
            max_playlist_length=None,
            seed_count=10,
            dry_run=True,
        )

    assert exc.value.exit_code == 1
