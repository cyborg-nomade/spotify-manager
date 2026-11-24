"""Construct independent cover resources with the shared public-provider gate."""

from pathlib import Path
from tempfile import gettempdir

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from spotify_manager.application.listening_covers import ListeningCoverEnrichment
from spotify_manager.infrastructure.listening.cover_cache import AlbumCoverCache
from spotify_manager.infrastructure.listening.cover_http import CoverHttpReads
from spotify_manager.infrastructure.listening.cover_source import MusicBrainzCoverSource
from spotify_manager.infrastructure.listening.lastfm_cover import LastFmCoverSource
from spotify_manager.infrastructure.listening.musicbrainz_gate import (
    MusicBrainzRequestGate,
)


class CoverEnvironment(BaseSettings):
    """Select one app-owned derived artwork cache per process."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    listening_cover_cache_dir: Path = Path(gettempdir()) / "spotify-listening-covers"
    lastfm_api_key: SecretStr | None = None


def listening_cover_enrichment(
    gate: MusicBrainzRequestGate,
) -> ListeningCoverEnrichment:
    """Construct cover cache/source resources outside application execution.

    Args:
        gate: App-owned MusicBrainz limiter shared with country lookups.

    Returns:
        Named explicit enrichment stage, independent of history and state.
    """
    settings = CoverEnvironment()
    key = settings.lastfm_api_key
    archive = MusicBrainzCoverSource(gate, CoverHttpReads())
    return ListeningCoverEnrichment(
        AlbumCoverCache(settings.listening_cover_cache_dir),
        archive,
        LastFmCoverSource(key.get_secret_value()) if key else None,
    )
