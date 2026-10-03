"""Spotify credential maintenance at the CLI compatibility boundary."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from spotipy import Spotify

from spotify_manager.client import RotatingSpotify


@dataclass(kw_only=True)
class SpotifyAuthCLI:
    """Refresh tokens through the original overridable Spotify client factory.

    Args:
        review_client: Original headless-capable interactive client factory.
        rotating_client_type: Original class used to recognize app rotation.
    """

    review_client: Callable[[], Spotify]
    rotating_client_type: type[RotatingSpotify]

    def _refresh_spotify_tokens(self) -> None:
        """Authenticate or force-refresh every configured Spotify app token."""
        spotify = self.review_client()
        if not isinstance(spotify, self.rotating_client_type):
            raise typer.BadParameter(
                "the configured client does not support app rotation"
            )
        try:
            refreshed = spotify.refresh_all_app_tokens()
        except Exception as exc:
            self._report_refresh_spotify_tokens_exception(exc)
        typer.echo(f"Spotify tokens ready: {', '.join(refreshed)}")

    def _report_refresh_spotify_tokens_exception(self, exc: Exception) -> Never:
        typer.echo(f"Spotify token refresh failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
