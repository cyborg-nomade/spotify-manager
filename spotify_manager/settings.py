"""Settings file."""

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """App setings."""

    model_config = SettingsConfigDict(env_file=".env")

    spotipy_client_id: str
    spotipy_client_secret: str
    spotipy_redirect_uri: str
    app5_client_id: str | None = None
    app5_client_secret: str | None = None
    app6_client_id: str | None = None
    app6_client_secret: str | None = None
    app7_client_id: str | None = None
    app7_client_secret: str | None = None
    app8_client_id: str | None = None
    app8_client_secret: str | None = None
    albums_to_add: int
    limit: int
    the_queue_playlist: str | None = None
    the_queue_2_playlist: str | None = None
    the_queue_3_playlist: str | None = None
    blast_from_the_past_playlist: str | None = None
    daily_mind_radio_playlist: str | None = None
    genre_reveal_playlist: str | None = None
