"""Construct independent public geography resources outside business execution."""

from pathlib import Path
from tempfile import gettempdir

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from spotify_manager.application.listening_origins import ListeningOriginEnrichment
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    MusicBrainzRequestGate,
)
from spotify_manager.infrastructure.listening.origin_cache import ArtistOriginCache
from spotify_manager.infrastructure.listening.origin_source import (
    MusicBrainzOriginSource,
)


class OriginEnvironment(BaseSettings):
    """Select one app-owned derived cache per process without new credentials."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    listening_origin_cache_dir: Path = Path(gettempdir()) / "spotify-listening-origins"


def listening_origin_enrichment(
    gate: MusicBrainzRequestGate | None = None,
) -> ListeningOriginEnrichment:
    """Own the country cache and public read provider for the web lifetime.

    Args:
        gate: App-owned provider limiter shared with album cover searches.

    Returns:
        Named explicit enrichment stage, separate from tags and canonical files.
    """
    settings = OriginEnvironment()
    return ListeningOriginEnrichment(
        ArtistOriginCache(settings.listening_origin_cache_dir),
        MusicBrainzOriginSource(gate),
    )
