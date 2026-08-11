"""Contract tests for small public Typer commands and CLI error rendering."""

from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy.exceptions import SpotifyException

from spotify_manager import main


def test_spotify_client_is_lazy_cached_and_reports_configuration_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spotify = object()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(main, "_client", None)

    def build(**kwargs: object) -> object:
        calls.append(kwargs)
        return spotify

    monkeypatch.setattr(main, "get_spotipy_client", build)
    assert main.client() is spotify
    assert main.client() is spotify
    assert calls == [{"event_callback": main.typer.echo}]

    monkeypatch.setattr(main, "_client", None)

    def fail(**_kwargs: object) -> None:
        raise main.SpotifyRedirectURIError("bad redirect")

    monkeypatch.setattr(main, "get_spotipy_client", fail)
    with pytest.raises(main.typer.Exit) as exc:
        main.client()
    assert exc.value.exit_code == 1
    assert "bad redirect" in capsys.readouterr().err


def test_review_client_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main, "_review_client", None)

    def fail(**_kwargs: object) -> None:
        raise main.SpotifyClientConfigurationError("partial app")

    monkeypatch.setattr(main, "get_spotipy_client", fail)
    with pytest.raises(main.typer.Exit) as exc:
        main.review_client()
    assert exc.value.exit_code == 1
    assert "partial app" in capsys.readouterr().err


def test_legacy_cli_commands_delegate_to_current_workflows(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spotify = object()
    calls: list[tuple[str, object | None]] = []
    monkeypatch.setattr(main, "client", lambda: spotify)
    monkeypatch.setattr(
        main,
        "compare_your_library_and_all_albums",
        lambda: calls.append(("compare", None)),
    )
    monkeypatch.setattr(
        main,
        "convert_your_library_file",
        lambda value: calls.append(("convert", value)),
    )
    monkeypatch.setattr(
        main,
        "run_monthly_routines",
        lambda value: calls.append(("monthly", value)),
    )
    monkeypatch.setattr(
        main,
        "update_total_album_list",
        lambda value, just_update: calls.append((f"update:{just_update}", value)),
    )
    monkeypatch.setattr(
        main,
        "restore_your_library_from_file",
        lambda value: calls.append(("restore", value)),
    )
    monkeypatch.setattr(
        main,
        "analyse_comparison",
        lambda value: calls.append(("analyse", value)),
    )
    monkeypatch.setattr(
        main,
        "count_artists_in_library",
        lambda: 42,
    )

    main.monthly_routines()
    main.update_total_albums(just_update=True)
    main.restore_your_library()
    main.compare_lib_files()
    main.analyse_comp()
    main.convert_lib()
    main.count_artists()

    assert [name for name, _value in calls] == [
        "compare",
        "convert",
        "monthly",
        "update:True",
        "restore",
        "compare",
        "analyse",
        "convert",
    ]
    assert all(value is spotify for _name, value in calls if value is not None)
    assert capsys.readouterr().out.strip() == "42"


@pytest.mark.parametrize(
    ("size", "formatted"),
    [
        (10, "10.0 B"),
        (1024, "1.0 KiB"),
        (1024**2, "1.0 MiB"),
        (1024**3, "1.0 GiB"),
    ],
)
def test_format_file_size_uses_binary_units(size: int, formatted: str) -> None:
    assert main.format_file_size(size) == formatted


def test_restore_sync_can_abort_and_reports_restore_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main.typer, "confirm", lambda *_args, **_kwargs: False)
    with pytest.raises(main.typer.Abort):
        main.restore_library_sync_command("run", yes=False)

    def fail(_run_id: str) -> None:
        raise main.library_sync.LibrarySyncRestoreError("backup missing")

    monkeypatch.setattr(main.library_sync, "restore_library_sync", fail)
    with pytest.raises(main.typer.Exit) as exc:
        main.restore_library_sync_command("run", yes=True)
    assert exc.value.exit_code == 1
    assert "backup missing" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [
        main.AmbiguousArtistError(
            "ambiguous",
            [{"artist": "Artist", "id": "artist-id"}],
        ),
        main.ArtistNotFoundError("missing"),
        main.SpotifyLookupResponseError("malformed"),
        SpotifyException(500, -1, "server failed"),
        RequestsConnectionError("connection reset"),
    ],
)
def test_artist_stats_reports_lookup_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    monkeypatch.setattr(main, "client", lambda: object())

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(main, "get_live_artist_library_stats", fail)
    with pytest.raises(main.typer.Exit) as exc:
        main.artist_stats(name="Artist", artist_id=None)
    assert exc.value.exit_code == 1
    assert capsys.readouterr().err


def test_artist_stats_validates_input_and_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(main.typer.BadParameter):
        main.artist_stats(name=None, artist_id=None)

    result = SimpleNamespace(model_dump_json=lambda **_kwargs: '{"artist": "A"}')
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(main, "get_live_artist_library_stats", lambda *_a, **_k: result)

    main.artist_stats(name=None, artist_id="artist-id")
    assert '{"artist": "A"}' in capsys.readouterr().out


@pytest.mark.parametrize(
    "error",
    [
        main.AmbiguousAlbumError(
            "ambiguous",
            [{"artist": "Artist", "album": "Album", "id": "album-id"}],
        ),
        main.AlbumNotFoundError("missing"),
        main.SpotifyLookupResponseError("malformed"),
        SpotifyException(500, -1, "server failed"),
        RequestsConnectionError("connection reset"),
    ],
)
def test_album_decision_reports_lookup_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    monkeypatch.setattr(main, "client", lambda: object())

    def fail(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(main, "evaluate_album_live", fail)
    with pytest.raises(main.typer.Exit) as exc:
        main.album_decision(
            name="Album",
            album_id=None,
            artist=None,
            threshold=0.5,
        )
    assert exc.value.exit_code == 1
    assert capsys.readouterr().err


def test_album_decision_validates_input_and_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(main.typer.BadParameter):
        main.album_decision(
            name=None,
            album_id=None,
            artist=None,
            threshold=0.5,
        )

    result = SimpleNamespace(model_dump_json=lambda **_kwargs: '{"decision": "keep"}')
    monkeypatch.setattr(main, "client", lambda: object())
    monkeypatch.setattr(main, "evaluate_album_live", lambda *_a, **_k: result)

    main.album_decision(
        name=None,
        album_id="album-id",
        artist="Artist",
        threshold=0.6,
    )
    assert '"decision": "keep"' in capsys.readouterr().out


def test_refresh_spotify_tokens_validates_client_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeRotatingSpotify:
        def __init__(self, error: Exception | None = None) -> None:
            self.error = error

        def refresh_all_app_tokens(self) -> tuple[str, ...]:
            if self.error is not None:
                raise self.error
            return ("app5", "app6")

    monkeypatch.setattr(main, "RotatingSpotify", FakeRotatingSpotify)
    monkeypatch.setattr(main, "review_client", lambda: object())
    with pytest.raises(main.typer.BadParameter):
        main.refresh_spotify_tokens()

    monkeypatch.setattr(
        main,
        "review_client",
        lambda: FakeRotatingSpotify(RuntimeError("auth failed")),
    )
    with pytest.raises(main.typer.Exit) as exc:
        main.refresh_spotify_tokens()
    assert exc.value.exit_code == 1
    assert "auth failed" in capsys.readouterr().err

    monkeypatch.setattr(main, "review_client", FakeRotatingSpotify)
    main.refresh_spotify_tokens()
    assert "app5, app6" in capsys.readouterr().out
