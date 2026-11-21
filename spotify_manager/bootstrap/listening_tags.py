"""Construct optional public-tag resources outside request and business paths."""

from pathlib import Path
from tempfile import gettempdir

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from spotify_manager.application.listening_tags import ListeningTagEnrichment
from spotify_manager.infrastructure.listening.tag_cache import ArtistTagCache
from spotify_manager.infrastructure.listening.tag_source import LastFmTagSource


class TagEnvironment(BaseSettings):
    """Read optional tag settings without requiring Spotify mutation credentials."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    lastfm_api_key: SecretStr | None = None
    listening_tag_cache_dir: Path = Path(gettempdir()) / "spotify-listening-tags"


def listening_tag_enrichment() -> ListeningTagEnrichment:
    """Own derived metadata and the configured public provider at app startup.

    Returns:
        Named application stage with independent, noncanonical cache resources.
    """
    settings = TagEnvironment()
    key = settings.lastfm_api_key
    source = LastFmTagSource(key.get_secret_value() if key else None)
    return ListeningTagEnrichment(
        ArtistTagCache(settings.listening_tag_cache_dir), source
    )
