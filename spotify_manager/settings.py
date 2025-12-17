"""Settings file."""

from pydantic import BaseSettings


class Settings(BaseSettings):
    """App setings."""

    spotipy_client_id: str
    spotipy_client_secret: str
    spotipy_redirect_uri: str
    albums_to_add: int
    limit: int

    class Config:
        """."""

        env_file = ".env"
