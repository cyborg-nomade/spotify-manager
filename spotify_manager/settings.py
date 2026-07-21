"""Settings file."""

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """App setings."""

    model_config = SettingsConfigDict(env_file=".env")

    spotipy_client_id: str
    spotipy_client_secret: str
    spotipy_redirect_uri: str
    albums_to_add: int
    limit: int
    the_queue_playlist: str | None = None
    the_queue_2_playlist: str | None = None
    the_queue_3_playlist: str | None = None
