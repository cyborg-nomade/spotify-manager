"""Keep complete Spotify links and credits readable in an ordinary terminal."""

from io import StringIO

from rich.console import Console
from rich.table import Table
from rich.text import Text

from spotify_manager.domain.history import Scrobble
from spotify_manager.domain.history_matching import SpotifyTrackMatch
from spotify_manager.interfaces.cli.display import ConsoleDisplay
from spotify_manager.interfaces.cli.track_matching import CliTrackMatching


def test_eighty_column_terminal_keeps_full_metadata_and_spotify_url() -> None:
    """Preserve copyable links rather than truncating them in narrow table columns."""
    output = StringIO()
    console = Console(file=output, width=80)
    interaction = CliTrackMatching(
        ConsoleDisplay(Console, Table, Text), console, console.status("Working")
    )
    candidate = SpotifyTrackMatch(
        "a" * 22,
        "spotify:track:" + "a" * 22,
        "Alternative song title",
        ("The Main Credited Artist", "The Entire Guest Credit"),
        "The Complete Catalog Album",
        1,
        0.5,
        0.5,
        1,
    )
    interaction._show(Scrobble("History", "Artist", "Album", 1), (candidate,))
    rendered = output.getvalue()
    assert "https://open.spotify.com/track/" + "a" * 22 in rendered
    assert "1. Alternative song title" in rendered
    assert "The Main Credited Artist, The Entire Guest Credit" in rendered
    assert "The Complete Catalog Album" in rendered
