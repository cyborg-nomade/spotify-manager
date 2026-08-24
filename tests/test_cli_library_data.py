"""CLI contracts for durable canonical library files."""

from typer.testing import CliRunner

from spotify_manager import main


def test_library_data_status_and_manual_seed() -> None:
    runner = CliRunner()

    seeded = runner.invoke(
        main.app,
        ["library-data-push", "--artifact", "albums", "--yes"],
    )
    status = runner.invoke(main.app, ["library-data-status"], terminal_width=180)

    assert seeded.exit_code == 0
    assert "Published albums at revision" in seeded.output
    assert status.exit_code == 0
    assert "Shared library data" in status.output
    assert "manual CLI" in status.output
    assert "publication" in status.output


def test_library_data_command_rejects_unknown_artifact() -> None:
    result = CliRunner().invoke(
        main.app,
        ["library-data-pull", "--artifact", "playlists"],
    )

    assert result.exit_code == 2
    assert "Unknown library-data artifact" in result.output
