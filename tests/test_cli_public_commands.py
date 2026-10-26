"""Contract tests for small public Typer commands and CLI error rendering."""

from dataclasses import dataclass
from dataclasses import field
from unittest.mock import Mock

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy.exceptions import SpotifyException

from spotify_manager import main
from spotify_manager.interfaces import lookup_operations
from spotify_manager.interfaces.cli.output import TYPER_OUTPUT
from spotify_manager.interfaces.operations import legacy_library as library_operations


def test_spotify_client_is_lazy_cached_and_reports_configuration_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Spotify client is lazy cached and reports configuration errors.

    Args:
        monkeypatch: Scoped external-boundary substitutions.
        capsys: Original capsys.
    """
    spotify = object()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(main, "_client", None)
    scenario = SpotifyClientIsLazyCachedAndReportsConfigurationErrorsScenario(
        calls=calls, spotify=spotify
    )
    monkeypatch.setattr(main, "get_spotipy_client", scenario.build)
    assert main.client() is spotify
    assert main.client() is spotify
    assert calls == [{"event_callback": TYPER_OUTPUT}]
    monkeypatch.setattr(main, "_client", None)
    monkeypatch.setattr(main, "get_spotipy_client", scenario.fail)
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
    """Verify legacy cli commands delegate to current workflows.

    Args:
        monkeypatch: Isolated replacements at the actual dependency owners.
        capsys: Captured operator-facing output.
    """
    spotify = object()
    calls = WorkflowCalls()
    monkeypatch.setattr(main, "client", Mock(return_value=spotify))
    monkeypatch.setattr(
        library_operations,
        "compare_your_library_and_all_albums",
        calls.compare,
    )
    monkeypatch.setattr(
        library_operations,
        "convert_your_library_file",
        calls.convert,
    )
    monkeypatch.setattr(
        library_operations,
        "run_monthly_routines",
        calls.monthly,
    )
    monkeypatch.setattr(
        library_operations,
        "update_total_album_list",
        calls.update,
    )
    monkeypatch.setattr(
        library_operations,
        "restore_your_library_from_file",
        calls.restore,
    )
    monkeypatch.setattr(
        library_operations,
        "analyse_comparison",
        calls.analyse,
    )
    monkeypatch.setattr(
        library_operations,
        "count_artists_in_library",
        Mock(return_value=42),
    )

    main.monthly_routines()
    main.update_total_albums(just_update=True)
    main.restore_your_library()
    main.compare_lib_files()
    main.analyse_comp()
    main.convert_lib()
    main.count_artists()

    assert [name for name, _value in calls.events] == [
        "compare",
        "convert",
        "monthly",
        "update:True",
        "restore",
        "compare",
        "analyse",
        "convert",
    ]
    assert all(value is spotify for _name, value in calls.events if value is not None)
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
    """Verify artist stats reports lookup failures.

    Args:
        monkeypatch: Isolated replacements at the actual dependency owners.
        capsys: Captured operator-facing output.
        error: Configured original failure.
    """
    monkeypatch.setattr(main, "client", Mock(return_value=object()))

    monkeypatch.setattr(
        lookup_operations, "get_live_artist_library_stats", Mock(side_effect=error)
    )
    with pytest.raises(main.typer.Exit) as exc:
        main.artist_stats(name="Artist", artist_id=None)
    assert exc.value.exit_code == 1
    assert capsys.readouterr().err


def test_artist_stats_validates_input_and_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify artist stats validates input and prints json.

    Args:
        monkeypatch: Isolated replacements at the actual dependency owners.
        capsys: Captured operator-facing output.
    """
    with pytest.raises(main.typer.BadParameter):
        main.artist_stats(name=None, artist_id=None)

    result = Mock(model_dump_json=Mock(return_value='{"artist": "A"}'))
    monkeypatch.setattr(main, "client", Mock(return_value=object()))
    monkeypatch.setattr(
        lookup_operations, "get_live_artist_library_stats", Mock(return_value=result)
    )

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
    """Verify album decision reports lookup failures.

    Args:
        monkeypatch: Isolated replacements at the actual dependency owners.
        capsys: Captured operator-facing output.
        error: Configured original failure.
    """
    monkeypatch.setattr(main, "client", Mock(return_value=object()))

    monkeypatch.setattr(
        lookup_operations, "evaluate_live_album", Mock(side_effect=error)
    )
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
    """Verify album decision validates input and prints json.

    Args:
        monkeypatch: Isolated replacements at the actual dependency owners.
        capsys: Captured operator-facing output.
    """
    with pytest.raises(main.typer.BadParameter):
        main.album_decision(
            name=None,
            album_id=None,
            artist=None,
            threshold=0.5,
        )

    result = Mock(model_dump_json=Mock(return_value='{"decision": "keep"}'))
    monkeypatch.setattr(main, "client", Mock(return_value=object()))
    monkeypatch.setattr(
        lookup_operations, "evaluate_live_album", Mock(return_value=result)
    )

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


@dataclass
class WorkflowCalls:
    """Record the command's original ordered workflow delegation.

    Args:
        events: Observed stage names and caller-owned clients.
    """

    events: list[tuple[str, object | None]] = field(default_factory=list)

    def compare(self) -> None:
        """Observe comparison before conversion and monthly work."""
        self.events.append(("compare", None))

    def convert(self, client: object) -> None:
        """Observe conversion with the caller's client.

        Args:
            client: Original client identity.
        """
        self.events.append(("convert", client))

    def monthly(self, client: object) -> None:
        """Observe monthly processing after conversion.

        Args:
            client: Original client identity.
        """
        self.events.append(("monthly", client))

    def update(self, client: object, just_update: bool) -> None:
        """Observe the explicit incremental-refresh flag.

        Args:
            client: Original client identity.
            just_update: Original CLI update-only flag.
        """
        self.events.append((f"update:{just_update}", client))

    def restore(self, client: object) -> None:
        """Observe restoration with the caller's client.

        Args:
            client: Original client identity.
        """
        self.events.append(("restore", client))

    def analyse(self, client: object) -> None:
        """Observe live comparison analysis with the caller's client.

        Args:
            client: Original client identity.
        """
        self.events.append(("analyse", client))


@dataclass
class SpotifyClientIsLazyCachedAndReportsConfigurationErrorsScenario:
    """Retain the original spotify client is lazy cached and reports configuration
    errors fixture.

    Args:
        calls: Original calls observation or resource.
        spotify: Original spotify observation or resource.
    """

    calls: list[dict[str, object]]
    spotify: object

    def build(self, **kwargs: object) -> object:
        """Execute the original build mock boundary.

        Args:
            kwargs: Original external mock argument.

        Returns:
            Original fixture result.
        """
        self.calls.append(kwargs)
        return self.spotify

    def fail(self, **_kwargs: object) -> None:
        """Execute the original fail mock boundary.

        Args:
            _kwargs: Original external mock argument.
        """
        raise main.SpotifyRedirectURIError("bad redirect")
