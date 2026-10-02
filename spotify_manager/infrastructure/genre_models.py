"""Original Pydantic request, progress and presentation contracts for Genre Reveal."""

from datetime import datetime

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from spotify_manager.domain.genres import completed_slugs
from spotify_manager.domain.genres import genre_name
from spotify_manager.domain.genres import genre_slug


MAX_GENRES = 6_132
MAX_SLUG_LENGTH = 256
MAX_GENRE_NAME_LENGTH = 256


def _validate_completed_slugs(slugs: list[str]) -> list[str]:
    return completed_slugs(slugs, MAX_SLUG_LENGTH)


class GenreRevealStateUpdate(BaseModel):
    """Client-provided genre-reveal progress.

    Args:
        completed: Original completed identities, normalized to first occurrence order.
        hide_done: Original visibility setting.
    """

    # Keep the published schema description independent of engineering docs.
    model_config = ConfigDict(
        json_schema_extra={"description": "Client-provided genre-reveal progress."}
    )

    completed: list[str] = Field(default_factory=list, max_length=MAX_GENRES)
    hide_done: bool = False

    @field_validator("completed")
    @classmethod
    def validate_completed(cls, value: list[str]) -> list[str]:
        """Validate and de-duplicate completed genre slugs.

        Args:
            value: Original string entries after boundary validation.

        Returns:
            Valid identities in first occurrence order.

        Raises:
            ValueError: An entry violates original completed-slug rules.
        """
        return _validate_completed_slugs(value)


class GenreRevealState(GenreRevealStateUpdate):
    """Persisted genre-reveal progress with server metadata.

    Args:
        completed: Original ordered completed identities.
        hide_done: Original visibility setting.
        version: Original persisted schema version.
        updated_at: Original last accepted progress time.
    """

    # Keep the published schema description independent of engineering docs.
    model_config = ConfigDict(
        json_schema_extra={
            "description": "Persisted genre-reveal progress with server metadata."
        }
    )

    version: int = 1
    updated_at: datetime | None = None


class GenreRevealRunRequest(BaseModel):
    """The first incomplete genre selected by the web route.

    Args:
        slug: Original lowercase alphanumeric route identity.
        name: Original unpadded display name.
    """

    # Keep the published schema description independent of engineering docs.
    model_config = ConfigDict(
        json_schema_extra={
            "description": "The first incomplete genre selected by the web route."
        }
    )

    slug: str = Field(min_length=1, max_length=MAX_SLUG_LENGTH)
    name: str = Field(min_length=1, max_length=MAX_GENRE_NAME_LENGTH)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        """Apply the same slug rules used by persisted progress.

        Args:
            value: Original genre identity.

        Returns:
            Valid lowercase alphanumeric identity.

        Raises:
            ValueError: An identity violates original request rules.
        """
        return genre_slug(value, MAX_SLUG_LENGTH)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Reject padded display names after boundary length validation.

        Args:
            value: Original already length-validated display name.

        Returns:
            Unchanged original display name.

        Raises:
            ValueError: A display name has leading or trailing whitespace.
        """
        return genre_name(value)


class GenreRevealSourcePreview(BaseModel):
    """Public links discovered for one Every Noise genre.

    Args:
        slug: Original validated genre identity.
        name: Original validated display name.
        every_noise_url: Original public genre page.
        source_playlist_id: Discovered primary playlist identity.
        source_playlist_uri: Discovered primary playlist URI.
        source_playlist_url: Original canonical public playlist link.
    """

    # Keep the published schema description independent of engineering docs.
    model_config = ConfigDict(
        json_schema_extra={
            "description": "Public links discovered for one Every Noise genre."
        }
    )

    slug: str
    name: str
    every_noise_url: str
    source_playlist_id: str
    source_playlist_uri: str
    source_playlist_url: str


class GenreRevealRunResult(GenreRevealSourcePreview):
    """Outcome of one completed genre-reveal Spotify operation.

    Args:
        destination_playlist_id: Original target identity.
        source_track_uris: Original ordered source markers.
        added_track_uris: Original accepted missing markers.
        already_present_track_uris: Original represented source markers.
        completed_at: Original completion time after accepted writes.
        **source_fields: Original public links defined by GenreRevealSourcePreview.
    """

    # Keep the published schema description independent of engineering docs.
    model_config = ConfigDict(
        json_schema_extra={
            "description": "Outcome of one completed genre-reveal Spotify operation."
        }
    )

    destination_playlist_id: str
    source_track_uris: list[str]
    added_track_uris: list[str]
    already_present_track_uris: list[str]
    completed_at: datetime
