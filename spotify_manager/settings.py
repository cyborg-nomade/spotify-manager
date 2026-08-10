"""Settings file."""

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    """App setings."""

    model_config = SettingsConfigDict(env_file=".env")

    spotipy_client_id: str
    spotipy_client_secret: str
    spotipy_redirect_uri: str
    app_password: str | None = None
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
    new_kids_on_the_block_playlist: str | None = None
    great_discoveries_2026_playlist: str | None = None
    unlucky_ones_playlist: str | None = None
    blast_from_the_past_playlist: str | None = None
    daily_mind_radio_playlist: str | None = None
    genre_reveal_playlist: str | None = None
    found_art_playlist: str | None = None
    new_wine_from_old_bottles_playlist: str | None = None
    wine_cellar_playlist: str | None = None
    new_vintage_playlist: str | None = None
    sauvignon_terre_neuve_playlist: str | None = None
    slow_listening_playlist: str | None = None
    reqeueue_for_a_dream_playlist: str | None = None
    palace_of_memory_playlist: str | None = None
    something_old_new_playlist: str | None = None
    discography_newfoundland_playlist: str | None = None
    discography_memory_lane_playlist: str | None = None
    discography_requeue_playlist: str | None = None
    lastfm_api_key: str | None = None
    lastfm_username: str | None = None
