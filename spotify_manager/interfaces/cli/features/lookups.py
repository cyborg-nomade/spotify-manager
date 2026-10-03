"""Explicit lookups CLI execution, prompts and presentation."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Never

import typer
from requests.exceptions import RequestException
from spotipy import Spotify
from spotipy.exceptions import SpotifyException

from spotify_manager.models.lookups import AlbumEvaluation
from spotify_manager.models.lookups import ArtistLibraryStats
from spotify_manager.processors.library_lookups import AlbumNotFoundError
from spotify_manager.processors.library_lookups import AmbiguousAlbumError
from spotify_manager.processors.library_lookups import AmbiguousArtistError
from spotify_manager.processors.library_lookups import ArtistNotFoundError
from spotify_manager.processors.library_lookups import SpotifyLookupResponseError


@dataclass(kw_only=True)
class LookupsCLI:
    """Execute and present lookups through explicit facade dependencies.

    Args:
        client: Client supplied by the caller.
        evaluate_album_live: Evaluate album live supplied by the caller.
        get_live_artist_library_stats: Original get live artist library stats boundary
            supplied by the facade.
    """

    client: Callable[..., Spotify]
    evaluate_album_live: Callable[..., AlbumEvaluation]
    get_live_artist_library_stats: Callable[..., ArtistLibraryStats]

    def _artist_stats(self, name: str, artist_id: str) -> None:
        """Show live liked-track and saved-release counts for an artist.

        Args:
            name: Name supplied by the caller.
            artist_id: Artist id supplied by the caller.
        """
        if not name and (not artist_id):
            raise typer.BadParameter("provide an artist NAME or --artist-id")
        try:
            stats = self.get_live_artist_library_stats(
                self.client(), name=name, artist_id=artist_id
            )
        except AmbiguousArtistError as exc:
            self._report_artist_stats_ambiguous_artist_failure(exc)
        except (ArtistNotFoundError, SpotifyLookupResponseError) as exc:
            self._report_artist_stats_artist_not_found_failure(exc)
        except SpotifyException as exc:
            self._report_artist_stats_spotify_spotify_failure(exc)
        except RequestException as exc:
            self._report_artist_stats_connection_request_exception(exc)
        typer.echo(stats.model_dump_json(indent=2))

    def _album_decision(
        self, name: str, album_id: str, artist: str, threshold: float
    ) -> None:
        """Evaluate an album against live Spotify Liked Songs state.

        Args:
            name: Name supplied by the caller.
            album_id: Album id supplied by the caller.
            artist: Artist supplied by the caller.
            threshold: Threshold supplied by the caller.
        """
        if not name and (not album_id):
            raise typer.BadParameter("provide an album NAME or --album-id")
        try:
            evaluation = self.evaluate_album_live(
                self.client(),
                name=name,
                album_id=album_id,
                artist=artist,
                threshold=threshold,
            )
        except AmbiguousAlbumError as exc:
            self._report_album_decision_ambiguous_album_failure(exc)
        except (AlbumNotFoundError, SpotifyLookupResponseError) as exc:
            self._report_album_decision_album_not_found_failure(exc)
        except SpotifyException as exc:
            self._report_album_decision_spotify_spotify_failure(exc)
        except RequestException as exc:
            self._report_album_decision_connection_request_exception(exc)
        typer.echo(evaluation.model_dump_json(indent=2))

    def _report_artist_stats_ambiguous_artist_failure(
        self, exc: AmbiguousArtistError
    ) -> Never:
        typer.echo(str(exc), err=True)
        for candidate in exc.candidates:
            typer.echo(f"  {candidate['artist']} ({candidate['id']})", err=True)
        raise typer.Exit(code=1) from exc

    def _report_album_decision_ambiguous_album_failure(
        self, exc: AmbiguousAlbumError
    ) -> Never:
        typer.echo(str(exc), err=True)
        for candidate in exc.candidates:
            typer.echo(
                (f"  {candidate['artist']} - {candidate['album']} ({candidate['id']})"),
                err=True,
            )
        raise typer.Exit(code=1) from exc

    def _report_artist_stats_artist_not_found_failure(
        self, exc: ArtistNotFoundError | SpotifyLookupResponseError
    ) -> Never:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    def _report_artist_stats_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        typer.echo(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"), err=True
        )
        raise typer.Exit(code=1) from exc

    def _report_artist_stats_connection_request_exception(
        self, exc: RequestException
    ) -> Never:
        typer.echo(
            (
                "Spotify could not be reached after several "
                "attempts. Please try again shortly."
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc

    def _report_album_decision_album_not_found_failure(
        self, exc: AlbumNotFoundError | SpotifyLookupResponseError
    ) -> Never:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    def _report_album_decision_spotify_spotify_failure(
        self, exc: SpotifyException
    ) -> Never:
        typer.echo(
            (f"Spotify request failed (HTTP {exc.http_status}): {exc.msg}"), err=True
        )
        raise typer.Exit(code=1) from exc

    def _report_album_decision_connection_request_exception(
        self, exc: RequestException
    ) -> Never:
        typer.echo(
            (
                "Spotify could not be reached after several "
                "attempts. Please try again shortly."
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc
