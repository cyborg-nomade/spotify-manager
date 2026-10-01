"""Retain genre discovery, SDK writes and presentation at the outer boundary."""

from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from pathlib import Path

from spotipy import Spotify

from spotify_manager.application.genre_values import GenreOutcome
from spotify_manager.domain.genres import GenrePlaylistSource
from spotify_manager.domain.genres import GenreSource
from spotify_manager.routines import genre_reveal as legacy


@dataclass
class LegacyGenreReveal:
    """Bind the original source reader, Spotify client and completed audit seam.

    Args:
        spotify: Caller-owned Spotify client.
        reader: Original public-page reader.
        path: Original audit location.
    """

    spotify: Spotify
    reader: legacy.PageReader
    path: Path
    result: legacy.GenreRevealRunResult = field(init=False)

    def source(self, slug: str, name: str) -> GenrePlaylistSource:
        """Discover the original source before reading destination membership.

        Args:
            slug: Original validated genre identity.
            name: Original validated display name.

        Returns:
            Typed original public links and ordered markers.
        """
        source = legacy.load_genre_playlist_source(slug, name, self.reader)
        preview = source.preview
        values = GenreSource(
            preview.slug,
            preview.name,
            preview.every_noise_url,
            preview.source_playlist_id,
            preview.source_playlist_uri,
            preview.source_playlist_url,
        )
        return GenrePlaylistSource(values, source.track_uris)

    def destination(self, playlist_id: str) -> frozenset[str]:
        """Retain original playlist membership observation.

        Args:
            playlist_id: Original destination identity.

        Returns:
            Original live destination identities.
        """
        return legacy.blast_from_past.load_playlist_state(
            self.spotify, playlist_id
        ).track_ids

    def follow(self, source: GenrePlaylistSource) -> None:
        """Accept the original library-save request before any marker append.

        Args:
            source: Discovered original source.
        """
        legacy._save_source_playlist(self.spotify, source)

    def append(self, destination: str, missing: tuple[str, ...]) -> None:
        """Accept the original ordered missing-marker append.

        Args:
            destination: Original target identity.
            missing: Original missing markers.
        """
        legacy._append_source_tracks(self.spotify, destination, missing)

    def clock(self) -> datetime:
        """Retain the original completion clock after accepted writes.

        Returns:
            Original current UTC time.
        """
        return legacy.datetime.now(UTC)

    def audit(self, outcome: GenreOutcome) -> None:
        """Construct the original presented result before accepting its audit.

        Args:
            outcome: Completed original business observations.
        """
        self.result = legacy.GenreRevealRunResult(
            **asdict(outcome.source),
            destination_playlist_id=outcome.destination_playlist_id,
            source_track_uris=list(outcome.source_track_uris),
            added_track_uris=list(outcome.added_track_uris),
            already_present_track_uris=list(outcome.already_present_track_uris),
            completed_at=outcome.completed_at,
        )
        legacy.append_genre_reveal_log(self.result, self.path)
