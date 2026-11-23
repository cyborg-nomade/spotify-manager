"""Construct independent public geography resources outside business execution."""

from pathlib import Path
from tempfile import gettempdir

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict

from spotify_manager.application.listening_origins import ListeningOriginEnrichment
from spotify_manager.bootstrap.library_data import DEFAULT_LIBRARY_DATA_REPO
from spotify_manager.infrastructure.huggingface.listening_origin_archive import (
    HubOriginArchive,
)
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
    listening_origin_durable: bool | None = None
    space_id: str | None = None
    spotify_manager_data_backend: str = "hub"
    spotify_manager_data_repo: str = DEFAULT_LIBRARY_DATA_REPO
    spotify_manager_data_token: SecretStr | None = None
    spotify_manager_state_token: SecretStr | None = None
    hf_token: SecretStr | None = None


def _origin_archive(settings: OriginEnvironment) -> HubOriginArchive | None:
    enabled = settings.listening_origin_durable
    if enabled is None:
        enabled = bool(settings.space_id)
    if not enabled or settings.spotify_manager_data_backend.casefold() != "hub":
        return None
    secret = (
        settings.spotify_manager_data_token
        or settings.spotify_manager_state_token
        or settings.hf_token
    )
    return HubOriginArchive(
        settings.spotify_manager_data_repo,
        secret.get_secret_value() if secret else None,
    )


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
        _origin_archive(settings),
    )
